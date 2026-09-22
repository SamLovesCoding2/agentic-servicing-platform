"""Compliance engine tests: rule semantics, tenant stacking, strictest-wins, fail-closed."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from taylor.compliance.registry import build_default_rules, build_engine, default_compliance_engine
from taylor.compliance.rules import (
    ActionContext,
    AuthMinimumRule,
    BaseRule,
    ContactPreferenceRule,
    DailyCapRule,
    DisclosureRule,
    MaxArrangementsRule,
    MinimumAmountRule,
    RuleDecision,
    SchedulingWindowRule,
    StateExclusionRule,
)

TODAY = datetime(2026, 9, 25, 12, 0, 0)


def ctx(**overrides) -> ActionContext:
    base = dict(
        action_type="schedule_payment",
        tenant="westpond",
        channel="sms",
        auth_level="step_up",
        customer_id="cust_001",
        account_id="ACC-001",
        amount=Decimal("300.00"),
        scheduled_date=TODAY.date() + timedelta(days=10),
        now=TODAY,
        account_state="UT",
    )
    base.update(overrides)
    return ActionContext(**base)


# ── Rule-level semantics ──────────────────────────────────────────────────────

class TestRules:
    def test_auth_minimum_requires_step_up(self):
        engine = build_engine([AuthMinimumRule()])
        assert engine.evaluate(ctx(auth_level="verified")).decision == RuleDecision.REQUIRE_STEP_UP
        assert engine.evaluate(ctx(auth_level="step_up")).decision == RuleDecision.ALLOW

    def test_minimum_amount_zero_dollar_killed(self):
        engine = build_engine([MinimumAmountRule(min_amount=Decimal("0.01"))])
        assert engine.evaluate(ctx(amount=Decimal("0.00"))).decision == RuleDecision.DENY
        assert engine.evaluate(ctx(amount=Decimal("0.01"))).decision == RuleDecision.ALLOW

    def test_scheduling_window_rejects_past_and_far_future(self):
        engine = build_engine([SchedulingWindowRule(min_days_out=1, max_days_out=30)])
        # Today (min_days_out=1 → earliest is tomorrow) — denied
        assert engine.evaluate(ctx(scheduled_date=TODAY.date())).decision == RuleDecision.DENY
        # 5 days out — allowed
        assert engine.evaluate(ctx(scheduled_date=TODAY.date() + timedelta(days=5))).decision == RuleDecision.ALLOW
        # 45 days out — denied
        assert engine.evaluate(ctx(scheduled_date=TODAY.date() + timedelta(days=45))).decision == RuleDecision.DENY

    def test_daily_cap(self):
        engine = build_engine([DailyCapRule(max_amount=Decimal("1000.00"))])
        assert engine.evaluate(ctx(amount=Decimal("1000.00"))).decision == RuleDecision.ALLOW
        assert engine.evaluate(ctx(amount=Decimal("1000.01"))).decision == RuleDecision.DENY

    def test_max_arrangements_requires_agent(self):
        engine = build_engine([MaxArrangementsRule(max_count=3)])
        assert engine.evaluate(ctx(existing_arrangements=2)).decision == RuleDecision.ALLOW
        assert engine.evaluate(ctx(existing_arrangements=3)).decision == RuleDecision.REQUIRE_AGENT

    def test_contact_preference_honors_sms_opt_out(self):
        engine = build_engine([ContactPreferenceRule()])
        assert engine.evaluate(ctx(contact_preferences={"sms_opted_out": True})).decision == RuleDecision.DENY
        assert engine.evaluate(ctx(contact_preferences={})).decision == RuleDecision.ALLOW

    def test_do_not_call_blocks_voice_only(self):
        engine = build_engine([ContactPreferenceRule()])
        assert engine.evaluate(ctx(channel="voice", contact_preferences={"do_not_call": True})).decision == RuleDecision.DENY
        # DNC does not block SMS
        assert engine.evaluate(ctx(channel="sms", contact_preferences={"do_not_call": True})).decision == RuleDecision.ALLOW

    def test_state_exclusion_requires_agent(self):
        engine = build_engine([StateExclusionRule(states=("CA", "TX"))])
        assert engine.evaluate(ctx(account_state="TX")).decision == RuleDecision.REQUIRE_AGENT
        assert engine.evaluate(ctx(account_state="UT")).decision == RuleDecision.ALLOW

    def test_disclosure_required_requires_agent_when_missing(self):
        engine = build_engine([DisclosureRule()])
        assert engine.evaluate(ctx(disclosures=("amount_disclosed",))).decision == RuleDecision.REQUIRE_AGENT
        assert engine.evaluate(
            ctx(disclosures=DisclosureRule.REQUIRED)
        ).decision == RuleDecision.ALLOW

    def test_rule_ignores_non_applicable_action(self):
        engine = build_engine([MinimumAmountRule()])
        # Not a payment — no opinion, defaults to allow
        assert engine.evaluate(ctx(action_type="search_faq", amount=Decimal("0.00"))).decision == RuleDecision.ALLOW

    def test_rule_ignores_other_tenant(self):
        engine = build_engine([DailyCapRule(max_amount=Decimal("100.00"), tenants=("westpond",))])
        # cpr tenant is exempt from westpond's cap
        assert engine.evaluate(ctx(tenant="cpr", amount=Decimal("500.00"))).decision == RuleDecision.ALLOW


# ── Strictest-wins combination ────────────────────────────────────────────────

class TestStrictestWins:
    def test_deny_beats_allow(self):
        rules = [
            MinimumAmountRule(min_amount=Decimal("0.01")),
            DailyCapRule(max_amount=Decimal("1000.00")),
        ]
        engine = build_engine(rules)
        # amount 0 violates the minimum (DENY) AND is under the cap (ALLOW)
        decision = engine.evaluate(ctx(amount=Decimal("0.00")))
        assert decision.decision == RuleDecision.DENY
        assert decision.blocked

    def test_require_agent_beats_require_step_up(self):
        rules = [
            AuthMinimumRule(),                              # step_up → ALLOW
            StateExclusionRule(states=("CA",)),
            MaxArrangementsRule(max_count=1),
        ]
        engine = build_engine(rules)
        decision = engine.evaluate(
            ctx(auth_level="verified", account_state="CA", existing_arrangements=2)
        )
        assert decision.decision == RuleDecision.REQUIRE_AGENT

    def test_require_step_up_when_other_rules_allow(self):
        engine = build_engine([AuthMinimumRule(), ContactPreferenceRule()])
        decision = engine.evaluate(ctx(auth_level="anonymous"))
        assert decision.decision == RuleDecision.REQUIRE_STEP_UP
        assert decision.requires_step_up
        assert not decision.blocked

    def test_all_allows_is_allow(self):
        engine = default_compliance_engine()
        decision = engine.evaluate(ctx())
        assert decision.decision == RuleDecision.ALLOW
        assert not decision.blocked

    def test_tenant_cap_stacks_with_global_cap(self):
        # Add a Westpond-specific cap that is TIGHTER than the global cap.
        rules = build_default_rules() + [
            DailyCapRule(max_amount=Decimal("900.00"), tenants=("westpond",))
        ]
        engine = build_engine(rules)
        # 1000 is under the global cap (2000) but over Westpond's (900) — denied.
        assert engine.evaluate(ctx(tenant="westpond", amount=Decimal("1000.00"))).decision == RuleDecision.DENY
        # CPR uses the global cap only.
        assert engine.evaluate(ctx(tenant="cpr", amount=Decimal("1000.00"))).decision == RuleDecision.ALLOW

    def test_matched_rules_reported(self):
        engine = default_compliance_engine()
        decision = engine.evaluate(ctx(amount=Decimal("0.00")))
        ids = {m.rule_id for m in decision.matched}
        assert "minimum_amount" in ids
        assert any(m.rule_id == "minimum_amount" and m.decision == RuleDecision.DENY for m in decision.matched)


# ── Fail-closed ───────────────────────────────────────────────────────────────

class TestFailClosed:
    def test_erroring_rule_denies_action(self):
        class ExplodingRule(BaseRule):
            def __init__(self):
                super().__init__("exploding", "always fails", reason_code="EXPLODE")

            def decide(self, context):
                raise RuntimeError("boom")

        engine = build_engine([ExplodingRule()])
        decision = engine.evaluate(ctx(amount=Decimal("300.00")))
        assert decision.decision == RuleDecision.DENY
        assert decision.blocked
        assert any(m.reason_code == "RULE_EVAL_ERROR" for m in decision.matched)

    def test_duplicate_rule_registration_rejected(self):
        engine = default_compliance_engine()
        with pytest.raises(ValueError):
            engine.register(AuthMinimumRule())
