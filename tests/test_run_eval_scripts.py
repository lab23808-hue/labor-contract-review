"""scripts/run_eval_samples.py 和 scripts/compare_eval_results.py 的单元测试。

这两个脚本本身不是包（scripts/ 下没有 __init__.py），用 sys.path 插入的
方式按模块名直接 import——和脚本的实际运行方式（python scripts/xxx.py）
是同一份代码，不是复制一份逻辑单独测。
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_eval_samples as rs  # noqa: E402
import compare_eval_results as ce  # noqa: E402


def test_not_run_report_never_claims_real_run():
    for stage in (2, 3, 4, 5, 6, 7):
        report = rs._not_run_report(stage)
        assert report["status"] == "not_run_in_sandbox"
        assert "local_command" in report and report["local_command"]
        assert "reason" in report and report["reason"]


def test_stage_1_offline_is_a_real_run_with_contracts():
    from evaluation.generate_contracts import build_all_contracts_with_parts

    pairs = build_all_contracts_with_parts()
    contracts = [c for c, _ in pairs]
    report = rs.run_stage_1(contracts, pairs)
    assert report["status"] == "real_run"
    assert report["result"]["required_citation_total"] > 0


def test_stage_6_offline_is_a_real_run_and_reports_known_limitation_gap():
    from evaluation.generate_contracts import build_all_contracts_with_parts

    pairs = build_all_contracts_with_parts()
    report = rs.run_stage_6_offline(pairs)
    assert report["status"] == "real_run"
    assert report["part"] == "rules_only"
    assert report["result"]["contracts_checked"] == 50
    assert "known_limitation_gap_count" in report["result"]


def test_cli_main_offline_all_stages_writes_result_file(tmp_path):
    out = tmp_path / "run.json"
    argv_backup = sys.argv
    try:
        sys.argv = ["run_eval_samples.py", "--stage", "all", "--output", str(out)]
        rs.main()
    finally:
        sys.argv = argv_backup
    assert out.exists()
    import json

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["stages"]["1"]["status"] == "real_run"
    assert data["stages"]["6"]["status"] == "real_run"
    for stage in ("2", "3", "4", "5", "7"):
        assert data["stages"][stage]["status"] == "not_run_in_sandbox"


def test_diff_metrics_reports_not_comparable_when_neither_side_ran():
    diff = ce._diff_metrics("2", None, None)
    assert diff["comparable"] is False


def test_diff_metrics_reports_not_comparable_when_only_one_side_ran():
    diff = ce._diff_metrics("1", {"coverage_rate": 1.0}, None)
    assert diff["comparable"] is False


def test_diff_metrics_computes_delta_when_both_sides_ran():
    before = {"recall": 0.5, "precision": 0.8}
    after = {"recall": 0.75, "precision": 0.8}
    diff = ce._diff_metrics("6", before, after)
    assert diff["comparable"] is True
    assert diff["fields"]["recall"]["delta"] == 0.25
    assert diff["fields"]["precision"]["delta"] == 0


def test_compare_cli_main_runs_against_two_real_result_files(tmp_path):
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    argv_backup = sys.argv
    try:
        sys.argv = ["run_eval_samples.py", "--stage", "1", "--output", str(out_a)]
        rs.main()
        sys.argv = ["run_eval_samples.py", "--stage", "1", "--output", str(out_b)]
        rs.main()

        diff_out = tmp_path / "diff.json"
        sys.argv = ["compare_eval_results.py", str(out_a), str(out_b), "--output", str(diff_out)]
        ce.main()
    finally:
        sys.argv = argv_backup
    assert diff_out.exists()
