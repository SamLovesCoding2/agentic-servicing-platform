"""Default policy set and engine factory.

Defaults model a real regulated servicing business:
  - Global rules apply to every tenant.
  - Westpond (charged-off auto loans) carries a tighter daily cap.
  - CPR (credit payment recovery) is stricter about when payments land.

New tenants register their deltas here; policy changes are code-reviews,
versioned with the application.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from taylor.compliance.engine import ComplianceEngine
from taylor.compliance.rules import (
    AuthMinimumRule,
    BaseRule,
    ContactPreferenceRule,
    DailyCapRule,
    MaxArrangementsRule,
    MinimumAmountRule,
    SchedulingWindowRule,
    StateExclusionRule,
)

DEFAULT_TENANT = "westpond"


def build_default_rules() -> list[BaseRule]:
    """The default policy set. Any tenant-specific rule stacks with the globals
    and, being stricter, wins via strictest-wins semantics."""
    return [
        AuthMinimumRule(),
        MinimumAmountRule(min_amount=Decimal("0.01")),
        SchedulingWindowRule(min_days_out=1, max_days_out=90),
        DailyCapRule(max_amount=Decimal("2000.00")),               # global
        DailyCapRule(max_amount=Decimal("1500.00"), tenants=("westpond",)),  # tighter for Westpond
        MaxArrangementsRule(max_count=5),
        ContactPreferenceRule(),
        StateExclusionRule(states=("CA", "TX")),
        # DisclosureRule intentionally NOT in defaults: it is registered by
        # tenants that require disclosure evidence before execution.
    ]


def build_engine(rules: Iterable[BaseRule] | None = None) -> ComplianceEngine:
    return ComplianceEngine(rules or build_default_rules())


def default_compliance_engine() -> ComplianceEngine:
    """The engine used at the execution boundary (registry) in production runs."""
    return build_engine()
