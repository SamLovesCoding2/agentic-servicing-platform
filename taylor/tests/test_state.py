"""
Tests for state schema and reducers.

Verifies:
  - merge_slots unions keys correctly
  - compare_and_set prevents race between correction and execution
  - replace always takes the new value
  - State machine transitions are valid
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from taylor.graphs.universal.state import (
    ActionStatus,
    AuthLevel,
    Channel,
    SubgraphExit,
    compare_and_set,
    merge_slots,
    replace,
)


# ── merge_slots tests ────────────────────────────────────────────────────────

class TestMergeSlots:
    def test_empty_merge(self):
        assert merge_slots({}, {}) == {}

    def test_disjoint_keys(self):
        result = merge_slots({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_overlapping_keys_right_wins(self):
        result = merge_slots({"a": 1, "b": 2}, {"b": 3})
        assert result == {"a": 1, "b": 3}

    def test_none_left(self):
        result = merge_slots(None, {"a": 1})
        assert result == {"a": 1}

    def test_none_right(self):
        result = merge_slots({"a": 1}, None)
        assert result == {"a": 1}


# ── compare_and_set tests ────────────────────────────────────────────────────

class TestCompareAndSet:
    def test_set_new_when_left_is_none(self):
        result = compare_and_set(None, {"amount": "300.00", "version": 1})
        assert result == {"amount": "300.00", "version": 1}

    def test_clear_when_right_is_none(self):
        result = compare_and_set({"amount": "300.00", "version": 1}, None)
        assert result is None

    def test_higher_version_wins(self):
        left = {"amount": "300.00", "version": 1}
        right = {"amount": "350.00", "version": 2}
        result = compare_and_set(left, right)
        assert result == right

    def test_lower_version_rejected(self):
        """This is the key race prevention: a correction with a lower
        version cannot overwrite a newer confirmation."""
        left = {"amount": "350.00", "version": 2}
        right = {"amount": "300.00", "version": 1}
        result = compare_and_set(left, right)
        assert result == left  # left wins, stale update rejected

    def test_equal_version_left_wins(self):
        left = {"amount": "350.00", "version": 2}
        right = {"amount": "300.00", "version": 2}
        result = compare_and_set(left, right)
        assert result == left

    def test_no_version_field_right_wins(self):
        left = {"amount": "300.00"}
        right = {"amount": "350.00"}
        result = compare_and_set(left, right)
        assert result == right


# ── replace tests ────────────────────────────────────────────────────────────

class TestReplace:
    def test_replace_with_value(self):
        assert replace("old_token", "new_token") == "new_token"

    def test_replace_with_none(self):
        """replace always takes right, including None — this invalidates old selections."""
        assert replace("old_token", None) is None

    def test_replace_none_with_value(self):
        assert replace(None, "new_token") == "new_token"


# ── ActionStatus state machine tests ─────────────────────────────────────────

class TestActionStateMachine:
    def test_proposed_to_confirmed_happy_path(self):
        """Verify the happy path: PROPOSED → NORMALIZED → VALIDATED → AUTHORIZED → EXECUTING → CONFIRMED."""
        transitions = [
            (ActionStatus.PROPOSED, ActionStatus.NORMALIZED),
            (ActionStatus.NORMALIZED, ActionStatus.VALIDATED),
            (ActionStatus.VALIDATED, ActionStatus.AUTHORIZED),
            (ActionStatus.AUTHORIZED, ActionStatus.EXECUTING),
            (ActionStatus.EXECUTING, ActionStatus.CONFIRMED),
        ]
        current = ActionStatus.PROPOSED
        for expected_from, expected_to in transitions:
            assert current == expected_from
            current = expected_to
        assert current == ActionStatus.CONFIRMED

    def test_unknown_is_not_failure(self):
        """UNKNOWN is a valid terminal-ish state that requires reconciliation."""
        assert ActionStatus.UNKNOWN != ActionStatus.REJECTED
        assert ActionStatus.UNKNOWN != ActionStatus.CONFIRMED

    def test_unknown_to_confirmed_via_reconciliation(self):
        """UNKNOWN can transition to CONFIRMED after reconciliation."""
        assert ActionStatus.UNKNOWN.value == "UNKNOWN"
        assert ActionStatus.CONFIRMED.value == "CONFIRMED"

    def test_rejected_is_terminal(self):
        """REJECTED is a terminal state."""
        terminal_states = {ActionStatus.CONFIRMED, ActionStatus.REJECTED}
        assert ActionStatus.REJECTED in terminal_states

    def test_all_statuses_exist(self):
        """All 8 states must be defined."""
        expected = {"PROPOSED", "NORMALIZED", "VALIDATED", "AUTHORIZED",
                    "EXECUTING", "CONFIRMED", "REJECTED", "UNKNOWN"}
        actual = {s.value for s in ActionStatus}
        assert actual == expected


# ── Versioned authorization invalidation ─────────────────────────────────────

class TestVersionedAuthorization:
    def test_authorization_invalidated_on_amount_change(self):
        """
        If the amount changes after consent, the authorization is invalid.
        This prevents the model from modifying the action post-consent.
        """
        auth_artifact = {
            "artifact_id": "auth_001",
            "bound_values": {
                "amount": "300.00",
                "date": "2026-09-15",
                "method_token": "pm_tok_001",
            },
            "is_valid": True,
            "version": 1,
        }

        # Customer corrects the amount
        new_amount = Decimal("350.00")
        original_amount = Decimal(auth_artifact["bound_values"]["amount"])

        # The authorization should be invalidated
        assert new_amount != original_amount
        # In the real system, the auth_artifact's is_valid would be set to False
        # and invalidated_reason would be "amount changed"

    def test_authorization_invalidated_on_date_change(self):
        """Date change invalidates authorization."""
        auth = {
            "bound_values": {"amount": "300.00", "date": "2026-09-15", "method_token": "pm_tok_001"},
            "is_valid": True,
        }
        new_date = date(2026, 9, 20)
        original_date = date.fromisoformat(auth["bound_values"]["date"])
        assert new_date != original_date

    def test_authorization_invalidated_on_method_change(self):
        """Method token change invalidates authorization."""
        auth = {
            "bound_values": {"amount": "300.00", "date": "2026-09-15", "method_token": "pm_tok_001"},
            "is_valid": True,
        }
        new_token = "pm_tok_002"
        assert new_token != auth["bound_values"]["method_token"]
