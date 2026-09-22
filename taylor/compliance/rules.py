"""Compliance rule model and built-in regulated-action rules.

Each rule is stateless: it maps an :class:`ActionContext` to a
:class:`RuleDecision`. The engine combines rule decisions with
strictest-wins semantics and fails closed on evaluation errors.

Rules are declared in code (versioned with the app) rather than as
runtime-editable data, so policy changes are reviewable and replayable
across deployments.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any


class RuleDecision(str, Enum):
    """Decision a single rule can produce, ordered mildest → strictest."""

    NO_OPINION = "no_opinion"          # Rule does not apply to this context
    ALLOW = "allow"
    REQUIRE_STEP_UP = "require_step_up"  # Allowed, but only after step-up auth
    REQUIRE_AGENT = "require_agent"    # Allowed only with human-agent oversight
    DENY = "deny"                      # Blocked outright


# Strictness ordering used by the engine (strictest wins).
STRICTNESS: dict[RuleDecision, int] = {
    RuleDecision.NO_OPINION: 0,
    RuleDecision.ALLOW: 1,
    RuleDecision.REQUIRE_STEP_UP: 2,
    RuleDecision.REQUIRE_AGENT: 3,
    RuleDecision.DENY: 4,
}


@dataclass(frozen=True)
class ActionContext:
    """Everything a rule needs to reach a decision. Fully injectable for tests.

    ``now`` defaults to the current time when None; tests pin it to make
    time-window rules deterministic.
    """

    action_type: str
    tenant: str = "westpond"
    channel: str = "sms"
    auth_level: str = "anonymous"
    customer_id: str = ""
    account_id: str | None = None
    amount: Decimal | None = None
    scheduled_date: date_type | None = None
    now: datetime | None = None
    account_state: str = ""
    existing_arrangements: int = 0
    contact_preferences: dict[str, bool] = field(default_factory=dict)
    disclosures: tuple[str, ...] = ()

    @property
    def effective_now(self) -> datetime:
        return self.now if self.now is not None else datetime.now()

    @property
    def is_sms_opted_out(self) -> bool:
        return bool(self.contact_preferences.get("sms_opted_out"))

    @property
    def is_do_not_call(self) -> bool:
        return bool(self.contact_preferences.get("do_not_call"))

    @property
    def has_step_up_auth(self) -> bool:
        return self.auth_level == "step_up"


class BaseRule(abc.ABC):
    """A single compliance rule. Stateless, tenant-aware, versioned by id."""

    rule_id: str
    description: str
    reason_code: str

    def __init__(
        self,
        rule_id: str,
        description: str,
        reason_code: str,
        applies_to: tuple[str, ...] = ("*",),
        tenants: tuple[str, ...] = ("*",),
    ) -> None:
        if not all(c.isalnum() or c in "_" for c in rule_id):
            raise ValueError(f"rule_id must be snake_case alnum: {rule_id!r}")
        self.rule_id = rule_id
        self.description = description
        self.reason_code = reason_code
        self.applies_to = applies_to
        self.tenants = tenants

    def applies(self, context: ActionContext) -> bool:
        if "*" not in self.applies_to and context.action_type not in self.applies_to:
            return False
        if "*" not in self.tenants and context.tenant not in self.tenants:
            return False
        return True

    @abc.abstractmethod
    def decide(self, context: ActionContext) -> RuleDecision:
        """Return the rule's decision for a context that this rule applies to."""

    def evaluate(self, context: ActionContext) -> RuleDecision:
        """Evaluate a rule against a context; NO_OPINION when it doesn't apply."""
        if not self.applies(context):
            return RuleDecision.NO_OPINION
        return self.decide(context)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.rule_id}>"


# ── Built-in rules ─────────────────────────────────────────────────────────────

class AuthMinimumRule(BaseRule):
    """Sensitive actions require step-up authentication at the execution boundary.

    Defense in depth: the router already blocks under-authenticated intents;
    this rule rechecks at the point of execution (the registry boundary).
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            rule_id="auth_minimum",
            description="Sensitive actions require step-up authentication",
            reason_code="AUTH_MINIMUM",
            applies_to=("schedule_payment", "update_phone_number"),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        if context.has_step_up_auth:
            return RuleDecision.ALLOW
        return RuleDecision.REQUIRE_STEP_UP


class MinimumAmountRule(BaseRule):
    """Payments below a minimum amount are denied.

    Explicitly kills the $0.00 payment anti-pattern: a zero-value submission
    is never a valid authorization target.
    """

    def __init__(self, min_amount: Decimal = Decimal("0.01"), **kwargs: Any) -> None:
        self.min_amount = min_amount
        super().__init__(
            rule_id="minimum_amount",
            description=f"Payment amount must be at least {min_amount}",
            reason_code="MIN_AMOUNT",
            applies_to=("schedule_payment",),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        if context.amount is None:
            return RuleDecision.NO_OPINION
        if context.amount < self.min_amount:
            return RuleDecision.DENY
        return RuleDecision.ALLOW


class SchedulingWindowRule(BaseRule):
    """Scheduled payments must fall inside a sane forward window.

    Past-dated payments and dates beyond the servicing horizon are denied.
    """

    def __init__(
        self,
        min_days_out: int = 1,
        max_days_out: int = 90,
        **kwargs: Any,
    ) -> None:
        self.min_days_out = min_days_out
        self.max_days_out = max_days_out
        super().__init__(
            rule_id="scheduling_window",
            description=f"Payment date must be between {min_days_out} and {max_days_out} days out",
            reason_code="SCHEDULE_WINDOW",
            applies_to=("schedule_payment",),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        if context.scheduled_date is None:
            return RuleDecision.NO_OPINION
        today = context.effective_now.date()
        earliest = today + timedelta(days=self.min_days_out)
        latest = today + timedelta(days=self.max_days_out)
        if context.scheduled_date < earliest or context.scheduled_date > latest:
            return RuleDecision.DENY
        return RuleDecision.ALLOW


class DailyCapRule(BaseRule):
    """Per-customer daily payment cap. Tenant-specific caps stack (strictest wins)."""

    def __init__(self, max_amount: Decimal, **kwargs: Any) -> None:
        self.max_amount = max_amount
        # Keep the rule_id snake-safe: "2000.00" -> "2000_00".
        safe = "".join(c if c.isalnum() else "_" for c in str(max_amount))
        super().__init__(
            rule_id=f"daily_cap_{safe}",
            description=f"Daily payment cap of {max_amount} per customer",
            reason_code="DAILY_CAP",
            applies_to=("schedule_payment",),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        if context.amount is None:
            return RuleDecision.NO_OPINION
        if context.amount > self.max_amount:
            return RuleDecision.DENY
        return RuleDecision.ALLOW


class MaxArrangementsRule(BaseRule):
    """Customers with too many active arrangements require an agent."""

    def __init__(self, max_count: int = 5, **kwargs: Any) -> None:
        self.max_count = max_count
        super().__init__(
            rule_id="max_arrangements",
            description=f"More than {max_count} active arrangements requires agent oversight",
            reason_code="MAX_ARRANGEMENTS",
            applies_to=("schedule_payment",),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        if context.existing_arrangements >= self.max_count:
            return RuleDecision.REQUIRE_AGENT
        return RuleDecision.ALLOW


class ContactPreferenceRule(BaseRule):
    """Honor channel opt-outs: never act via a channel the customer opted out of.

    Applies to every action: a do-not-call customer is never engaged by phone,
    and an SMS opt-out is honored even for servicing actions on that channel.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            rule_id="contact_preference",
            description="Honor customer channel opt-outs (SMS opt-out, do-not-call)",
            reason_code="CONTACT_PREFERENCE",
            applies_to=("*",),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        if context.channel == "sms" and context.is_sms_opted_out:
            return RuleDecision.DENY
        if context.channel == "voice" and context.is_do_not_call:
            return RuleDecision.DENY
        return RuleDecision.ALLOW


class StateExclusionRule(BaseRule):
    """Actions in excluded states require a licensed agent."""

    def __init__(self, states: tuple[str, ...], **kwargs: Any) -> None:
        self.states = states
        super().__init__(
            rule_id="state_exclusion",
            description=f"Actions on accounts in {', '.join(states)} require an agent",
            reason_code="STATE_EXCLUSION",
            applies_to=("schedule_payment", "arrangement"),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        if context.account_state in self.states:
            return RuleDecision.REQUIRE_AGENT
        return RuleDecision.ALLOW


class DisclosureRule(BaseRule):
    """Proposed actions must carry the disclosures they claim to have shown."""

    REQUIRED = (
        "amount_disclosed",
        "date_disclosed",
        "method_disclosed",
        "no_guarantee_claim",
    )

    def __init__(self, required: tuple[str, ...] = REQUIRED, **kwargs: Any) -> None:
        self.required = required
        super().__init__(
            rule_id="disclosure_required",
            description="All required disclosures must be present before execution",
            reason_code="DISCLOSURE_REQUIRED",
            applies_to=("schedule_payment",),
            **kwargs,
        )

    def decide(self, context: ActionContext) -> RuleDecision:
        missing = set(self.required) - set(context.disclosures)
        if missing:
            return RuleDecision.REQUIRE_AGENT
        return RuleDecision.ALLOW
