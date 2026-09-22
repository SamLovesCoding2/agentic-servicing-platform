"""Strictest-wins, fail-closed compliance evaluation."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from taylor.compliance.rules import (
    STRICTNESS,
    ActionContext,
    BaseRule,
    RuleDecision,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuleMatch:
    """A rule that produced a verdict for a given evaluation."""

    rule_id: str
    decision: RuleDecision
    reason_code: str
    description: str = ""
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "decision": self.decision.value,
            "reason_code": self.reason_code,
            "description": self.description,
            "detail": self.detail,
        }


@dataclass
class ComplianceDecision:
    """The combined outcome of evaluating every applicable rule."""

    decision: RuleDecision = RuleDecision.ALLOW
    matched: list[RuleMatch] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Action cannot proceed: deny or require-human-oversight."""
        return self.decision in (RuleDecision.DENY, RuleDecision.REQUIRE_AGENT)

    @property
    def requires_step_up(self) -> bool:
        return self.decision == RuleDecision.REQUIRE_STEP_UP

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "blocked": self.blocked,
            "requires_step_up": self.requires_step_up,
            "matched_rules": [m.to_dict() for m in self.matched],
        }


class ComplianceEngine:
    """Evaluates an ActionContext against a rule set.

    Strictest-wins: of all applicable rule verdicts, the most restrictive
    wins (DENY > REQUIRE_AGENT > REQUIRE_STEP_UP > ALLOW).

    Fail-closed: if any applicable rule raises during evaluation, the
    decision becomes DENY with a RULE_EVAL_ERROR match. An erroring rule
    can never silently let an action through.
    """

    def __init__(self, rules: Iterable[BaseRule] | None = None) -> None:
        self._rules: list[BaseRule] = list(rules or [])

    def register(self, rule: BaseRule) -> None:
        if any(r.rule_id == rule.rule_id for r in self._rules):
            raise ValueError(f"Rule already registered: {rule.rule_id}")
        self._rules.append(rule)

    @property
    def rules(self) -> list[BaseRule]:
        return list(self._rules)

    def evaluate(self, context: ActionContext) -> ComplianceDecision:
        decision = RuleDecision.ALLOW
        matched: list[RuleMatch] = []

        for rule in self._rules:
            try:
                rule_decision = rule.evaluate(context)
            except Exception as exc:  # noqa: BLE001 — fail closed on any rule error
                logger.warning("Compliance rule %s failed, denying action", rule.rule_id, exc_info=True)
                matched.append(
                    RuleMatch(
                        rule_id=rule.rule_id,
                        decision=RuleDecision.DENY,
                        reason_code="RULE_EVAL_ERROR",
                        description=rule.description,
                        detail=f"rule evaluation error: {exc}",
                    )
                )
                rule_decision = RuleDecision.DENY

            if rule_decision is RuleDecision.NO_OPINION:
                continue

            matched.append(
                RuleMatch(
                    rule_id=rule.rule_id,
                    decision=rule_decision,
                    reason_code=rule.reason_code,
                    description=rule.description,
                )
            )

            if STRICTNESS[rule_decision] > STRICTNESS[decision]:
                decision = rule_decision

        return ComplianceDecision(decision=decision, matched=matched)

    def evaluate_action(self, **context_fields) -> ComplianceDecision:
        """Convenience wrapper: build an ActionContext from keyword fields."""
        return self.evaluate(ActionContext(**context_fields))
