"""对比两次 `scripts/run_eval_samples.py` 产出的结果 JSON（知识库补全前/后、
不同模型配置、不同规则版本之间的对比），输出到标准输出 + 可选写文件。

只做"读两份结果、对齐同名字段、算差值"，不重新跑任何实验、不猜测缺失字段。
两份结果里都没跑的阶段（status=not_run_in_sandbox）会被明确标注为
"两次都未运行"，不会被当成 0 和 0 比较出一个假的"无变化"结论。

用法：
    python scripts/compare_eval_results.py before.json after.json
    python scripts/compare_eval_results.py before.json after.json --output diff.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 每个阶段里，值得单独列出数值差异的指标字段（嵌套在 stage report 的
# result/rules_part.result 里）。只比较这些字段，避免把整段 contract_reports
# 这种明细列表也拿来做无意义的"差异"。
_METRIC_FIELDS = {
    "1": ["required_citation_total", "found_count", "missing_count", "coverage_rate"],
    "6": [
        "total_expected_hits",
        "total_actual_hits",
        "total_matched",
        "missed_count",
        "false_positive_count",
        "known_limitation_gap_count",
        "recall",
        "precision",
    ],
    "7": [
        "precision",
        "recall",
        "f1",
        "missed_count",
        "false_positive_count",
        "legal_basis_accuracy",
        "avg_latency_seconds",
        "p95_latency_seconds",
        "total_tokens",
        "total_cost",
    ],
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_stage_metrics(report: dict) -> Optional[dict]:
    """从一个 stage 的 report 里取出可比较的指标字典；拿不到就返回 None
    （status 不是 real_run，或者这个阶段本来就没有我们关心的 result 字段）。
    """
    if report.get("status") == "real_run":
        return report.get("result")
    if "rules_part" in report and report["rules_part"].get("status") == "real_run":
        return report["rules_part"].get("result")
    return None


def _diff_metrics(stage: str, before: Optional[dict], after: Optional[dict]) -> dict:
    fields = _METRIC_FIELDS.get(stage, [])
    if before is None and after is None:
        return {"comparable": False, "reason": "两次都没有真实运行这个阶段"}
    if before is None or after is None:
        return {
            "comparable": False,
            "reason": "只有一次真实运行了这个阶段（before_ran={}, after_ran={}）".format(
                before is not None, after is not None
            ),
        }
    diffs = {}
    for field in fields:
        b, a = before.get(field), after.get(field)
        if b is None and a is None:
            continue
        delta = None
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            delta = round(a - b, 4)
        diffs[field] = {"before": b, "after": a, "delta": delta}
    return {"comparable": True, "fields": diffs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="较早一次 run_eval_samples.py 的结果 JSON")
    parser.add_argument("after", type=Path, help="较新一次 run_eval_samples.py 的结果 JSON")
    parser.add_argument("--output", type=Path, default=None, help="把对比结果写成 JSON（可选）")
    args = parser.parse_args()

    before_data = _load(args.before)
    after_data = _load(args.after)

    all_stages = sorted(set(before_data.get("stages", {})) | set(after_data.get("stages", {})), key=int)

    comparison: dict[str, Any] = {
        "before_file": str(args.before),
        "after_file": str(args.after),
        "before_run_at": before_data.get("run_at"),
        "after_run_at": after_data.get("run_at"),
        "before_mode": before_data.get("mode"),
        "after_mode": after_data.get("mode"),
        "stages": {},
    }

    print(f"对比 {args.before} (运行于 {before_data.get('run_at')}) -> {args.after} (运行于 {after_data.get('run_at')})\n")

    for stage in all_stages:
        before_report = before_data.get("stages", {}).get(stage)
        after_report = after_data.get("stages", {}).get(stage)
        before_metrics = _get_stage_metrics(before_report) if before_report else None
        after_metrics = _get_stage_metrics(after_report) if after_report else None
        diff = _diff_metrics(stage, before_metrics, after_metrics)
        comparison["stages"][stage] = diff

        print(f"阶段 {stage}:")
        if not diff["comparable"]:
            print(f"  不可比较：{diff['reason']}")
            continue
        if not diff["fields"]:
            print("  没有定义/取到可比较的指标字段")
        for field, vals in diff["fields"].items():
            arrow = "" if vals["delta"] is None else (f" (Δ={vals['delta']:+})" if vals["delta"] else " (无变化)")
            print(f"  {field}: {vals['before']} -> {vals['after']}{arrow}")
        print()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"对比结果已写入 {args.output}")


if __name__ == "__main__":
    main()
