"""运行 50 份评估合同，输出检索/规则/LLM 指标。

用法：
    python scripts/run_eval_samples.py --fake-llm
    python scripts/run_eval_samples.py --strategy bm25 --fake-llm
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from core import ReviewSource  # noqa: E402
from evaluation.diagnostics import experiment6_rule_layer_check  # noqa: E402
from evaluation.generate_contracts import build_all_contracts_with_parts  # noqa: E402
from evaluation.metrics import extract_article, mean, recall_at_k, reciprocal_rank  # noqa: E402
from evaluation.schemas import ContractAnswer  # noqa: E402
from infra.llm.client import build_deepseek_client  # noqa: E402
from infra.storage import ContractManager  # noqa: E402
from retrieval import BM25Backend, DenseBackend, KnowledgeLoader, LegalKnowledgeRetriever, build_embedder  # noqa: E402
from domain.agents.review_agent import ClauseReviewer  # noqa: E402
from domain.rules import RuleChecker  # noqa: E402
from workflow.review_workflow import run_review  # noqa: E402

EVAL_DIR = PROJECT_ROOT / "data" / "eval_samples"
ANSWERS_DIR = EVAL_DIR / "answers"
RESULTS_DIR = PROJECT_ROOT / "data" / "eval_results"
REPORT_MD = PROJECT_ROOT / "docs" / "EVAL_REPORT.md"


class _FakeLLM:
    model = "fake-llm"

    def chat(self, messages, **kwargs):
        return json.dumps(
            {
                "risk": False,
                "risk_level": "none",
                "reason": "fake-llm：未做真实判断",
                "legal_basis": [],
                "suggestion": "",
            },
            ensure_ascii=False,
        )

    def chat_with_tool(self, messages, tool_schema, temperature=0.0):
        raise RuntimeError("fake-llm 不支持工具调用")


def _build_retriever(strategy: str) -> LegalKnowledgeRetriever:
    if strategy == "bm25":
        evidences = KnowledgeLoader(None).load_directory(settings.KNOWLEDGE_DIR)
        return LegalKnowledgeRetriever(BM25Backend(evidences))
    if strategy == "dense":
        backend = DenseBackend(embedding_function=build_embedder())
        return LegalKnowledgeRetriever(backend)
    if strategy == "hybrid":
        from retrieval.backends.hybrid import HybridBackend

        evidences = KnowledgeLoader(None).load_directory(settings.KNOWLEDGE_DIR)
        dense = DenseBackend(embedding_function=build_embedder())
        lexical = BM25Backend(evidences)
        return LegalKnowledgeRetriever(HybridBackend(dense=dense, lexical=lexical))
    raise ValueError(f"未知检索策略：{strategy}")


def _load_answers(limit: int | None) -> list[ContractAnswer]:
    answers = []
    for path in sorted(ANSWERS_DIR.glob("*.json")):
        answers.append(ContractAnswer.model_validate_json(path.read_text(encoding="utf-8")))
    return answers[:limit] if limit else answers


def _run_one(answer: ContractAnswer, retriever, llm_client) -> dict:
    with tempfile.TemporaryDirectory(prefix="eval_contract_") as tmp:
        root = Path(tmp)
        source = root / f"{answer.sample_id}.txt"
        source.write_text(answer.full_text, encoding="utf-8", newline="")
        manager = ContractManager(root_dir=root / "contracts")
        contract = manager.create_contract(source)
        reviewer = ClauseReviewer(retriever, llm_client)
        report = run_review(contract.contract_id, manager, reviewer, RuleChecker())

        clauses = sorted(manager.get_clauses(contract.contract_id), key=lambda c: c.start_char)
        gold = sorted(answer.clauses, key=lambda c: c.order)
        llm_by_clause = {
            r.clause_id: r for r in report.results if r.source == ReviewSource.LLM
        }

        recalls = []
        rrs = []
        risk_hits = 0
        level_hits = 0
        llm_total = 0
        aligned = 0
        for idx, gold_clause in enumerate(gold):
            if idx >= len(clauses):
                break
            aligned += 1
            result = llm_by_clause.get(clauses[idx].clause_id)
            if result is None:
                continue
            llm_total += 1
            if bool(result.risk) == bool(gold_clause.risk):
                risk_hits += 1
            if result.risk_level.value == (gold_clause.risk_level or "none"):
                level_hits += 1
            if gold_clause.legal_basis:
                retrieved = [e.article or "" for e in result.evidences]
                r = recall_at_k(gold_clause.legal_basis, retrieved, k=5)
                rr = reciprocal_rank(gold_clause.legal_basis, retrieved, k=5)
                if r is not None:
                    recalls.append(r)
                    rrs.append(rr)

    return {
        "sample_id": answer.sample_id,
        "clauses": len(gold),
        "aligned": aligned,
        "llm_total": llm_total,
        "risk_hits": risk_hits,
        "level_hits": level_hits,
        "recall_at_5": mean(recalls),
        "mrr_at_5": mean(rrs),
    }


def _write_report(result: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    (RESULTS_DIR / "eval_report.json").write_text(payload, encoding="utf-8")
    (RESULTS_DIR / f"eval_report_{result['strategy']}.json").write_text(payload, encoding="utf-8")

    m = result["metrics"]
    lines = [
        "# 评估报告",
        "",
        f"- 运行时间：{result['run_at']}",
        f"- 检索策略：`{result['strategy']}`",
        f"- Fake LLM：`{result['fake_llm']}`",
        f"- 合同数：{result['contracts']}",
        "",
        "## 检索指标（gold legal_basis 的 article 是否在 top-5）",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| Recall@5 | {m['retrieval']['recall_at_5']} |",
        f"| MRR@5 | {m['retrieval']['mrr_at_5']} |",
        f"| 有 gold 的条款数 | {m['retrieval']['count']} |",
        "",
        "## 规则层指标",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| precision | {m['rule']['precision']} |",
        f"| recall | {m['rule']['recall']} |",
        f"| false_positive | {m['rule']['false_positive_count']} |",
        f"| missed | {m['rule']['missed_count']} |",
        "",
        "## LLM 风险判定",
        "",
        "| 指标 | 值 |",
        "|---|---:|",
        f"| risk 一致率 | {m['llm']['risk_accuracy']} |",
        f"| risk_level 一致率 | {m['llm']['level_accuracy']} |",
        f"| 可对齐条款数 | {m['llm']['count']} |",
        "",
        "> fake-llm 模式下 LLM 始终返回 none，LLM 指标不代表真实模型质量。",
    ]
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fake-llm", action="store_true", help="使用 fake LLM，避免真实 token 消耗")
    parser.add_argument("--strategy", default=settings.RETRIEVAL_STRATEGY, choices=["bm25", "dense", "hybrid"])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    answers = _load_answers(args.limit)
    retriever = _build_retriever(args.strategy)
    llm_client = _FakeLLM() if args.fake_llm else build_deepseek_client()

    per_contract = []
    all_recalls = []
    all_rrs = []
    risk_hits = level_hits = llm_total = 0
    for answer in answers:
        row = _run_one(answer, retriever, llm_client)
        per_contract.append(row)
        risk_hits += row["risk_hits"]
        level_hits += row["level_hits"]
        llm_total += row["llm_total"]
        # 逐合同均值在 _run_one 里已经聚合；这里重新累计用于全局均值（按合同等权）
        if row["recall_at_5"] is not None:
            all_recalls.append(row["recall_at_5"])
            all_rrs.append(row["mrr_at_5"])

    rule_result = experiment6_rule_layer_check(build_all_contracts_with_parts()[: len(answers)])

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "strategy": args.strategy,
        "fake_llm": args.fake_llm,
        "contracts": len(answers),
        "metrics": {
            "retrieval": {
                "recall_at_5": mean(all_recalls),
                "mrr_at_5": mean(all_rrs),
                "count": sum(1 for row in per_contract if row["recall_at_5"] is not None),
            },
            "rule": {
                "precision": rule_result["precision"],
                "recall": rule_result["recall"],
                "false_positive_count": rule_result["false_positive_count"],
                "missed_count": rule_result["missed_count"],
            },
            "llm": {
                "risk_accuracy": round(risk_hits / llm_total, 4) if llm_total else None,
                "level_accuracy": round(level_hits / llm_total, 4) if llm_total else None,
                "count": llm_total,
            },
        },
        "per_contract": per_contract,
    }
    _write_report(result)
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    print(f"报告已写入 {RESULTS_DIR / 'eval_report.json'} 和 {REPORT_MD}")


if __name__ == "__main__":
    main()
