"""
Tests for the output filter.

Verifies:
  - Word-boundary-aware (doesn't rewrite inside other words)
  - Case-preserving (Loan → Contract, LOAN → CONTRACT, loan → contract)
  - Streaming-safe (works on partial text chunks)
  - Configurable replacement map
"""

from __future__ import annotations

import pytest

from taylor.output.output_filter import filter_output, make_filter, DEFAULT_REPLACEMENTS


class TestWordBoundary:
    def test_simple_replacement(self):
        assert "loan" not in filter_output("I have a loan to pay")
        assert "contract" in filter_output("I have a loan to pay")

    def test_no_replacement_inside_words(self):
        """Word-boundary-aware: doesn't touch 'loan' inside other words."""
        result = filter_output("The loanable amount is $500")
        assert "loanable" in result  # not changed
        assert "contractable" not in result

    def test_punctuation_boundaries(self):
        assert filter_output("Pay off your loan.") == "Pay off your contract."

    def test_start_of_string(self):
        assert filter_output("loan payment") == "contract payment"

    def test_end_of_string(self):
        assert filter_output("my loan") == "my contract"


class TestCasePreservation:
    def test_lowercase(self):
        assert filter_output("my loan") == "my contract"

    def test_title_case(self):
        assert filter_output("My Loan") == "My Contract"

    def test_all_caps(self):
        assert filter_output("MY LOAN") == "MY CONTRACT"

    def test_mixed_case_preserves_replacement(self):
        """Mixed case (e.g., 'LoAn') uses replacement as-is."""
        result = filter_output("my LoAn")
        assert "contract" in result.lower()


class TestMultipleReplacements:
    def test_multiple_words(self):
        result = filter_output("The lender told the borrower about the loan")
        assert "creditor" in result
        assert "customer" in result
        assert "contract" in result
        assert "lender" not in result
        assert "borrower" not in result
        assert "loan" not in result

    def test_plural(self):
        result = filter_output("I have two loans")
        assert result == "I have two contracts"


class TestStreamingSafe:
    def test_partial_chunk_at_boundary(self):
        """Filter works on chunks that might split a word."""
        # In real streaming, chunks might split words.
        # The filter should still work on complete words within chunks.
        chunk1 = "Your loan "
        chunk2 = "payment is due"
        filtered1 = filter_output(chunk1)
        filtered2 = filter_output(chunk2)
        assert "contract" in filtered1
        assert "loan" not in filtered1

    def test_empty_string(self):
        assert filter_output("") == ""

    def test_no_matches(self):
        original = "Hello, how can I help you?"
        assert filter_output(original) == original


class TestCustomReplacements:
    def test_custom_map(self):
        custom = {"auto": "vehicle", "car": "automobile"}
        fn = make_filter(custom)
        assert "vehicle" in fn("I need to fix my auto")
        assert "automobile" in fn("My car is broken")

    def test_custom_empty_map(self):
        fn = make_filter({})
        assert fn("loan loan loan") == "loan loan loan"
