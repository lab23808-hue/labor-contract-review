"""Rule Checker + 结果合并 真实端到端验证脚本（独立测试流程，不修改任何已有模块）。

验证目标（对应架构确认里的核心场景）：
    一份合同有多条 Clause，绝大多数走主线路（RAG+LLM）就能正常出结果，只有
    少数条款需要 RuleChecker 补充；merge_review_results 之后的列表长度
    = 主线路结果数 + 规则结果数，不是条款数；被规则命中的条款，LLM 结果和
    规则结果都完整保留，不会互相覆盖、不会丢信息。

主线路（Clause → generate_query → RAG → Evidence → DeepSeek → ReviewResult）
用真实 BGE-M3 + 真实 DeepSeek；RuleChecker 是纯本地正则规则，不需要网络。

前提：
    1. 已经跑过 scripts/build_knowledge_base.py，data/chroma/ 里有正式知识库；
    2. .env 里配置了 DEEPSEEK_API_KEY。

用法：
    python scripts/verify_rules_pipeline.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.review_agent import ClauseReviewer, ReviewError  # noqa: E402
from config import settings  # noqa: E402
from document import ClauseSplitter  # noqa: E402
from rag import LegalKnowledgeRetriever  # noqa: E402
from rules import RuleChecker, merge_review_results  # noqa: E402
from _common import (  # noqa: E402
    build_real_llm_client_or_exit,
    load_real_embedder_or_exit,
    open_knowledge_base_or_exit,
)
from _samples import RULES_SAMPLE  # noqa: E402


def main() -> None:
    print("[1/4] 加载真实 BGE-M3 embedding（首次运行会下载模型权重）...")
    embedder = load_real_embedder_or_exit()
    print("      完成\n")

    kb = open_knowledge_base_or_exit(embedder)  # 读取 data/chroma/ 里正式的知识库（只读）

    print("[2/4] 构造真实 DeepSeek 客户端...")
    llm_client = build_real_llm_client_or_exit()
    print(f"      model={llm_client.model}\n")

    retriever = LegalKnowledgeRetriever(kb, top_k=settings.RETRIEVAL_TOP_K)
    reviewer = ClauseReviewer(retriever, llm_client, top_k=settings.RETRIEVAL_TOP_K)

    clauses = [c for c in ClauseSplitter().split(RULES_SAMPLE, contract_id="verify_rules_demo") if c.original_text.strip()]
    print(f"[3/4] 合同共切分出 {len(clauses)} 条 Clause，逐条跑主线路 RAG+LLM...\n")

    llm_results = []
    failed_clause_ids = []
    for clause in clauses:
        try:
            result = reviewer.review(clause)
            llm_results.append(result)
            print(f"    [{clause.clause_id}] 主线路完成：risk_level={result.risk_level.value}")
            print(f"        reason: {result.reason}")
            print(f"        legal_basis: {result.legal_basis}")
            print(f"        suggestion: {result.suggestion}")
        except ReviewError as exc:
            failed_clause_ids.append(clause.clause_id)
            print(f"    [{clause.clause_id}] 主线路失败：{exc}")

    print(f"\n主线路结果：{len(llm_results)} 条成功，{len(failed_clause_ids)} 条失败")

    print("\n[4/4] RuleChecker 补充检查（不需要网络，不依赖主线路结果）...")
    rule_results = RuleChecker().check(clauses)
    print(f"      规则命中 {len(rule_results)} 条：")
    for r in rule_results:
        target = r.clause_id or f"related={r.related_clause_ids}"
        print(f"    - rule_id={r.rule_id}  clause={target}  risk_level={r.risk_level.value}")
        print(f"      reason: {r.reason}")

    merged = merge_review_results(llm_results, rule_results)

    print("\n" + "=" * 70)
    print("合并结果校验")
    print("=" * 70)
    print(f"条款总数：           {len(clauses)}")
    print(f"主线路成功结果数：    {len(llm_results)}")
    print(f"规则补充结果数：      {len(rule_results)}")
    print(f"合并后最终结果数：    {len(merged)}")
    expected = len(llm_results) + len(rule_results)
    status = "✅ 符合预期（= 主线路 + 规则，不是条款数）" if len(merged) == expected else "❌ 不符合预期！"
    print(f"预期结果数（相加）：  {expected}  {status}")

    # 找出同时有 LLM 结果和规则结果的条款，验证两者共存、没有互相覆盖
    llm_clause_ids = {r.clause_id for r in llm_results if r.clause_id}
    rule_clause_ids = {r.clause_id for r in rule_results if r.clause_id}
    overlapping = llm_clause_ids & rule_clause_ids
    print(f"\n同时存在 LLM 结果和规则结果的条款：{overlapping or '（无）'}")
    for clause_id in overlapping:
        print(f"\n--- {clause_id} 的两条结果都保留 ---")
        for r in merged:
            if r.clause_id == clause_id:
                print(f"  [source={r.source.value}] risk_level={r.risk_level.value}")
                print(f"      reason: {r.reason}")
                print(f"      legal_basis: {r.legal_basis}")
                print(f"      suggestion: {r.suggestion}")


if __name__ == "__main__":
    main()
