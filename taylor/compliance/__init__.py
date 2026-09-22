"""Compliance engine for regulated customer interactions (M2).

A stateless, strictest-wins, fail-closed policy engine evaluated at the
action boundary. Rules are small, testable, tenant-aware units; the engine
combines their verdicts and the *most restrictive* decision wins. Any rule
evaluation error fails closed to DENY.

Design principles (mirroring the production system):
  - Stateless: every evaluation takes an ActionContext and returns a decision.
  - Strictest-wins: DENY > REQUIRE_AGENT > REQUIRE_STEP_UP > ALLOW.
  - Fail-closed: an erroring rule denies the action, never silently allows.
  - Tenant-aware: rules can target tenants or apply globally.
"""

from .engine import ComplianceDecision, ComplianceEngine, RuleMatch
from .registry import build_default_rules, default_compliance_engine
from .rules import ActionContext, BaseRule, RuleDecision

__all__ = [
    "ActionContext",
    "BaseRule",
    "ComplianceDecision",
    "ComplianceEngine",
    "RuleDecision",
    "RuleMatch",
    "build_default_rules",
    "default_compliance_engine",
]
