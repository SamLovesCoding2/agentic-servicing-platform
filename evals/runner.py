"""Deterministic, data-driven evaluation runner.

Usage:

    python -m evals.runner --cases evals/cases.json --fail-under 1.0
    python -m evals.runner --cases evals/cases.json --json-out eval-report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taylor.graphs.universal.state import AuthLevel, Channel
from taylor.observability.tracing import redact
from taylor.runtime.text_runtime import TextRuntime


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    utterance: str
    channel: str
    auth_level: str
    expected: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvalCase:
        required = ("id", "category", "utterance", "expected")
        missing = [field for field in required if field not in value]
        if missing:
            raise ValueError(f"evaluation case is missing fields: {', '.join(missing)}")
        return cls(
            id=str(value["id"]),
            category=str(value["category"]),
            utterance=str(value["utterance"]),
            channel=str(value.get("channel", "sms")),
            auth_level=str(value.get("auth_level", "verified")),
            expected=dict(value["expected"]),
        )


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    category: str
    passed: bool
    checks: tuple[str, ...]
    actual: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "passed": self.passed,
            "checks": list(self.checks),
            "actual": redact(self.actual),
        }


@dataclass(frozen=True)
class EvalReport:
    total: int
    passed: int
    failed: int
    pass_rate: float
    categories: dict[str, dict[str, int]]
    results: tuple[EvalResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "categories": self.categories,
            "results": [result.as_dict() for result in self.results],
        }


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _check_expected(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    checks: list[str] = []
    for field in ("route", "exit_state", "gate_passed", "success_language_allowed"):
        if field not in expected:
            continue
        if actual.get(field) != expected[field]:
            checks.append(f"{field}: expected {expected[field]!r}, got {actual.get(field)!r}")

    reply = actual.get("reply", "").lower()
    for phrase in expected.get("reply_contains", []):
        if phrase.lower() not in reply:
            checks.append(f"reply_contains: missing {phrase!r}")
    for phrase in expected.get("reply_not_contains", []):
        if phrase.lower() in reply:
            checks.append(f"reply_not_contains: found {phrase!r}")
    return checks


async def run_cases(
    cases: list[EvalCase],
    runtime: TextRuntime | None = None,
) -> EvalReport:
    """Run cases against one deterministic runtime and return a report."""
    runtime = runtime or TextRuntime(force_deterministic=True)
    results: list[EvalResult] = []

    for case in cases:
        result = await runtime.run_turn(
            utterance=case.utterance,
            conversation_id=f"eval-{case.id}",
            customer_id="eval-customer",
            auth_level=AuthLevel(case.auth_level),
            channel=Channel(case.channel),
        )
        gate = result.get("gate_result") or {}
        actual = {
            "route": _value(result.get("route")),
            "exit_state": _value(result.get("exit_state")),
            "gate_passed": bool(gate.get("gate_passed", False)),
            "success_language_allowed": bool(result.get("success_language_allowed", False)),
            "reply": result.get("reply", ""),
        }
        checks = _check_expected(case.expected, actual)
        results.append(
            EvalResult(
                case_id=case.id,
                category=case.category,
                passed=not checks,
                checks=tuple(checks),
                actual=actual,
            )
        )

    category_counts: dict[str, dict[str, int]] = {}
    for result in results:
        counts = category_counts.setdefault(result.category, {"total": 0, "passed": 0, "failed": 0})
        counts["total"] += 1
        counts["passed" if result.passed else "failed"] += 1
    passed = sum(result.passed for result in results)
    total = len(results)
    return EvalReport(
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=passed / total if total else 1.0,
        categories=category_counts,
        results=tuple(results),
    )


def load_cases(path: str | Path) -> list[EvalCase]:
    """Load and validate JSON evaluation cases."""
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("evaluation case file must contain a JSON list")
    return [EvalCase.from_dict(value) for value in values]


def format_summary(report: EvalReport) -> str:
    lines = [
        f"Evaluation: {report.passed}/{report.total} passed "
        f"({report.pass_rate:.1%}), {report.failed} failed",
    ]
    for category, counts in sorted(report.categories.items()):
        lines.append(
            f"  {category}: {counts['passed']}/{counts['total']} passed"
        )
    for result in report.results:
        if not result.passed:
            lines.append(f"  FAIL {result.case_id}: {'; '.join(result.checks)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic agent evaluations")
    parser.add_argument("--cases", default="evals/cases.json")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--fail-under", type=float, default=1.0)
    args = parser.parse_args()

    report = asyncio.run(run_cases(load_cases(args.cases)))
    print(format_summary(report))
    if args.json_out:
        args.json_out.write_text(
            json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0 if report.pass_rate >= args.fail_under else 1


if __name__ == "__main__":
    raise SystemExit(main())
