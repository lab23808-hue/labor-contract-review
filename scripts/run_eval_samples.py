"""运行 50 份评估合同样本的诊断实验（CLI 入口），支持：

- 跑全部 50 份，或用 --sample 只跑某一份；
- 用 --stage 只跑某个阶段（1-7，对应任务说明里的实验1-7），或 --stage all 跑全部；
- 默认 --mode offline：绕开真实 LLM/RAG/LangGraph，只用标准答案里的条款
  直接构造 `schemas.Clause` 喂给真实 `rules.RuleChecker`（即"实验6规则部分"
  和"实验1"——这两个在本沙箱里能真实执行，不是模拟）；
- --mode online：尝试跑真正需要 langchain_text_splitters / chromadb /
  openai / langgraph 的阶段（2/3/4/5/7，以及 6 里的 LLM 部分）。在本沙箱里
  这些依赖不可用，脚本会**诚实报告缺什么、给出本地该跑的命令**，
  绝不会自动降级成假结果去冒充真实评估——这是任务明确要求的红线。
- 把结果写成结构化 JSON 持久化（不是只打印一遍就丢掉），供
  `scripts/compare_eval_results.py` 做前后对比。

用法示例：
    python scripts/run_eval_samples.py                          # offline，全部可跑阶段
    python scripts/run_eval_samples.py --stage 1
    python scripts/run_eval_samples.py --stage 6 --sample clear_risk_12
    python scripts/run_eval_samples.py --mode online --stage 7  # 需要本地真实环境
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from evaluation.diagnostics import experiment1_knowledge_coverage, experiment6_rule_layer_check  # noqa: E402
from evaluation.generate_contracts import build_all_contracts_with_parts  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent.parent / "data" / "eval_samples" / "results"

# 每个本沙箱不可执行阶段：缺的依赖名 + 本地该跑的命令。命令是基于本项目
# 实际入口写的（不是抄一个通用示例），本地装好依赖、配好 .env 之后可以直接跑。
_NOT_RUNNABLE_HERE = {
    2: {
        "name": "条款切分检查（标准答案条款 vs document.splitter.ClauseSplitter 真实切分结果对比）",
        "missing": "langchain_text_splitters（document/splitter.py 模块顶层 import，本沙箱无法 pip install）",
        "local_command": (
            "pip install -r requirements.txt && "
            "python -c \"from document.splitter import ClauseSplitter; "
            "from evaluation.generate_contracts import build_all_contracts; "
            "[ClauseSplitter().split(c.full_text) for c in build_all_contracts()]\" "
            "# 需要你自己补一个对比脚本：把切分结果的 clause 边界/原文和标准答案逐条对比，"
            "不是只跑通不报错"
        ),
    },
    3: {
        "name": "RAG 独立检索检查（Recall@K / MRR / 不相关证据占比）",
        "missing": "langchain_chroma + sentence-transformers（rag/database.py, rag/knowledge_loader.py）"
        "，以及需要先用真实 BGE-M3 构建好 data/chroma 向量库",
        "local_command": (
            "pip install -r requirements.txt && "
            "python scripts/build_knowledge_base.py && "
            "python scripts/run_eval_samples.py --mode online --stage 3"
            "  # 需要你自己补充人工标注的「条款->应检索到的法条」对照表，"
            "不能只用系统自己的检索结果当 ground truth"
        ),
    },
    4: {
        "name": "区分切分问题与检索问题（标准条款文本 vs 实际切分文本分别检索对比）",
        "missing": "同实验 2 + 实验 3 的依赖",
        "local_command": "pip install -r requirements.txt && python scripts/build_knowledge_base.py && "
        "python scripts/run_eval_samples.py --mode online --stage 4",
    },
    5: {
        "name": "区分检索问题与 LLM 判断问题（原始系统结果 vs 标准条款文本 vs 标准法律依据 三组对照）",
        "missing": "openai 客户端 + DEEPSEEK_API_KEY（llm/client.py）+ 实验3的依赖",
        "local_command": "pip install -r requirements.txt && "
        "# 在 .env 里配置 DEEPSEEK_API_KEY 和可用的模型名（见 config/settings.py 顶部注释）\n"
        "python scripts/build_knowledge_base.py && "
        "python scripts/run_eval_samples.py --mode online --stage 5"
        "  # 需固定 temperature/模型版本并重复跑几次，处理 LLM 非确定性",
    },
    6: {
        "name": "规则和合并检查——LLM 原始结果 / 规则原始结果 / 合并后结果 三者独立对比（规则部分已在 offline 模式真实跑过，见 --stage 6 的 offline 输出；这里缺的是 LLM 部分）",
        "missing": "openai 客户端 + DEEPSEEK_API_KEY + langgraph（workflows/review_workflow.py）",
        "local_command": "pip install -r requirements.txt && "
        "# 配置 .env 后：\n"
        "python scripts/build_knowledge_base.py && "
        "python scripts/run_eval_samples.py --mode online --stage 6",
    },
    7: {
        "name": "端到端质量评估（全部 50 份合同：风险级别 P/R/F1、法律依据准确率、建议可执行性、耗时、token/成本）",
        "missing": "openai + langgraph + langchain_chroma 全链路（workflows/review_workflow.py 整条链）",
        "local_command": "pip install -r requirements.txt && "
        "# 配置 .env 后：\n"
        "python scripts/build_knowledge_base.py && "
        "python scripts/run_eval_samples.py --mode online --stage 7 --output "
        "data/eval_samples/results/e2e_$(date +%Y%m%d_%H%M).json",
    },
}


def _not_run_report(stage: int) -> dict:
    info = _NOT_RUNNABLE_HERE[stage]
    return {
        "stage": stage,
        "status": "not_run_in_sandbox",
        "name": info["name"],
        "reason": f"缺少依赖/环境：{info['missing']}",
        "local_command": info["local_command"],
        "note": "本沙箱明确不允许用 FakeLLM/模拟结果代替此阶段——没跑就是没跑，不伪造数值。",
    }


def _try_online_stage(stage: int) -> dict:
    """--mode online 时真正尝试跑一下，失败就诚实报告失败原因（不是直接假定不可跑）。"""
    try:
        if stage in (2, 4):
            from document.splitter import ClauseSplitter  # noqa: F401
        if stage in (3, 4, 5, 6, 7):
            from rag.database import ChromaKnowledgeBase  # noqa: F401
        if stage in (5, 6, 7):
            from llm.client import build_deepseek_client  # noqa: F401
        if stage == 7:
            from workflows.review_workflow import build_review_graph  # noqa: F401
    except ImportError as exc:
        report = _not_run_report(stage)
        report["reason"] = f"{report['reason']}（import 时报错：{exc}）"
        return report

    return {
        "stage": stage,
        "status": "not_implemented_yet",
        "name": _NOT_RUNNABLE_HERE[stage]["name"],
        "reason": (
            "依赖已经能 import 成功，说明本地环境具备条件，但本脚本目前只有"
            "“检测依赖是否可用”这一步，真正调用 ClauseSplitter/RAG/LLM/LangGraph "
            "跑对比实验的逻辑需要你在本地按 docs/EVAL_DIAGNOSTICS.md 里该阶段的"
            "说明补充（本沙箱从未跑过这部分代码，不能假装验证过）。"
        ),
    }


def run_stage_1(contracts, pairs) -> dict:
    return {"stage": 1, "status": "real_run", "result": experiment1_knowledge_coverage(contracts, settings.KNOWLEDGE_DIR)}


def run_stage_6_offline(pairs) -> dict:
    return {"stage": 6, "status": "real_run", "part": "rules_only", "result": experiment6_rule_layer_check(pairs)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="all", help="1-7 或 all（默认 all，只跑 offline 模式下真正可跑的阶段）")
    parser.add_argument("--sample", default=None, help="只处理某个 sample_id（目前用于 stage 1/6）")
    parser.add_argument("--mode", choices=["offline", "online"], default="offline")
    parser.add_argument("--output", type=Path, default=None, help="结果 JSON 输出路径（默认带时间戳自动生成）")
    args = parser.parse_args()

    pairs = build_all_contracts_with_parts()
    if args.sample:
        pairs = [(c, p) for c, p in pairs if c.sample_id == args.sample]
        if not pairs:
            raise SystemExit(f"找不到 sample_id={args.sample}")
    contracts = [c for c, _ in pairs]

    stages: list[int]
    if args.stage == "all":
        stages = [1, 2, 3, 4, 5, 6, 7]
    else:
        stages = [int(args.stage)]

    results: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "sample_filter": args.sample,
        "contracts_count": len(contracts),
        "stages": {},
    }

    for stage in stages:
        if stage == 1:
            results["stages"]["1"] = run_stage_1(contracts, pairs)
        elif stage == 6 and args.mode == "offline":
            results["stages"]["6"] = run_stage_6_offline(pairs)
        elif args.mode == "offline":
            results["stages"][str(stage)] = _not_run_report(stage)
        else:  # online 模式，尝试探测依赖
            if stage == 6:
                # 规则部分永远先真跑一遍，再追加 LLM 部分的探测结果
                rules_part = run_stage_6_offline(pairs)
                llm_part = _try_online_stage(6)
                results["stages"]["6"] = {"rules_part": rules_part, "llm_part": llm_part}
            else:
                results["stages"][str(stage)] = _try_online_stage(stage)

    output_path = args.output
    if output_path is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"run_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"结果已写入 {output_path}")
    for stage_key, report in results["stages"].items():
        status = report.get("status") or f"rules_part={report.get('rules_part', {}).get('status')}"
        print(f"  阶段 {stage_key}: {status}")


if __name__ == "__main__":
    main()
