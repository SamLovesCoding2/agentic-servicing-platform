from pathlib import Path

from evals.runner import EvalCase, load_cases, run_cases


def test_case_file_is_data_driven():
    cases = load_cases(Path(__file__).with_name("cases.json"))

    assert len(cases) == 8
    assert all(isinstance(case, EvalCase) for case in cases)


async def test_deterministic_evaluation_suite_passes():
    cases = load_cases(Path(__file__).with_name("cases.json"))

    report = await run_cases(cases)

    assert report.total == 8
    assert report.failed == 0
    assert report.pass_rate == 1.0
