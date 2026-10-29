"""完整 LangGraph 流程的真实端到端验证脚本（独立测试流程，不修改任何已有模块）。

这是目前项目里"从合同文件到最终结果"最完整的一次真实调用：
    合同文件 → ContractManager 登记 → workflows.review_workflow.run_review()
      内部依次跑：Contract Loading → (LLM Review ∥ Rule Check) → Merge → Report Assembly
    → 打印最终 State → 用最终 State 重新构造一次 ReviewReport

用真实 BGE-M3 + 真实 DeepSeek + 真实 LangGraph（需要已经 pip install -r
requirements.txt，包含 langgraph）。

前提：
    1. 已经跑过 scripts/build_knowledge_base.py，data/index/chroma/ 里有正式知识库；
    2. .env 里配置了 DEEPSEEK_API_KEY。

用法：
    python scripts/verify_full_pipeline.py                  # 用内置示例合同
    python scripts/verify_full_pipeline.py --file 合同.txt   # 用你自己的 txt 合同
"""

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from domain.agents.review_agent import ClauseReviewer  # noqa: E402
from config import settings  # noqa: E402
from infra.storage import ContractManager  # noqa: E402
from retrieval import LegalKnowledgeRetriever  # noqa: E402
from domain.rules import RuleChecker  # noqa: E402
from workflow.review_workflow import run_review  # noqa: E402
from _common import (  # noqa: E402
    build_real_llm_client_or_exit,
    load_real_embedder_or_exit,
    open_knowledge_base_or_exit,
)
from _samples import FULL_PIPELINE_DEMO  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=str, default=None, help="要审查的合同 txt 文件路径；不传则用内置示例合同")
    parser.add_argument("--top-k", type=int, default=settings.RETRIEVAL_TOP_K, help=f"每个条款检索几条法律依据（默认 {settings.RETRIEVAL_TOP_K}）")
    args = parser.parse_args()

    print("[1/4] 加载真实 BGE-M3 embedding（首次运行会下载模型权重）...")
    embedder = load_real_embedder_or_exit()
    print("      完成\n")

    kb = open_knowledge_base_or_exit(embedder)  # 读取 data/index/chroma/ 里正式的知识库（只读）

    print("[2/4] 构造真实 DeepSeek 客户端...")
    llm_client = build_real_llm_client_or_exit()
    print(f"      model={llm_client.model}\n")

    retriever = LegalKnowledgeRetriever(kb, top_k=args.top_k)
    reviewer = ClauseReviewer(retriever, llm_client, top_k=args.top_k)
    rule_checker = RuleChecker()
    contract_manager = ContractManager()  # 默认根目录 data/runtime/contracts/

    # 准备合同文件：用户指定的，或者内置示例（写到临时文件）
    if args.file:
        contract_path = Path(args.file)
    else:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
        tmp.write(FULL_PIPELINE_DEMO)
        tmp.close()
        contract_path = Path(tmp.name)
        print(f"[提示] 未指定 --file，使用内置示例合同（临时文件：{contract_path}）\n")

    print("[3/4] 登记合同并跑完整 LangGraph 流程...")
    contract = contract_manager.create_contract(contract_path)
    print(f"      contract_id = {contract.contract_id}")

    # run_review 对外的返回值是 ReviewReport（Stage 2 调整：不再是裸的
    # LangGraph state dict），本脚本不再需要自己重新拼一次报告。
    report = run_review(contract.contract_id, contract_manager, reviewer, rule_checker)
    print("      流程跑完\n")

    print("[4/4] ReviewReport 汇总")
    print("=" * 70)
    print(f"最终结果数：      {len(report.results)}")
    print(f"审查失败条款数：   {len(report.failed_clauses)}")
    for f in report.failed_clauses:
        print(f"    - {f.clause_id}: {f.error}")

    print(f"\n整体风险等级：overall_risk_level = {report.overall_risk_level.value}")
    print(f"风险分布：summary = {report.summary.model_dump()}")

    print("\n各条最终结果：")
    for r in report.results:
        target = r.clause_id or f"related={r.related_clause_ids}"
        print(f"  [{r.source.value}] clause={target}  risk_level={r.risk_level.value}")
        print(f"      reason: {r.reason}")


if __name__ == "__main__":
    main()
