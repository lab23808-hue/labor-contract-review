"""evaluation/diagnostics.py 的单元测试（实验 1 + 实验 6 规则部分）。

这两个实验都不需要 langchain_text_splitters/chromadb/openai/langgraph——
实验 1 只读文本文件，实验 6 只用 schemas.Clause + 真实的 rules.RuleChecker，
两者在本沙箱里都能真实运行，测试本身也是真实执行，不是降级模拟。
"""

from pathlib import Path

from evaluation.diagnostics import (
    _extract_article_labels,
    _parse_citation,
    experiment1_knowledge_coverage,
    experiment6_rule_layer_check,
)
from evaluation.generate_contracts import build_all_contracts, build_all_contracts_with_parts
from evaluation.schemas import ClauseAnswer, ContractAnswer, ContractSampleType, VerificationStatus


def test_parse_citation_extracts_article_number():
    assert _parse_citation("《劳动合同法》第二十条") == "第二十条"
    assert _parse_citation("《劳动合同法》第八十七条第一款") == "第八十七条"
    assert _parse_citation("没有条号的引用") is None


def test_extract_article_labels_finds_all_articles(tmp_path):
    f = tmp_path / "law.txt"
    f.write_text("第一条　内容。\n\n第二条　内容。\n", encoding="utf-8")
    assert _extract_article_labels(f.read_text(encoding="utf-8")) == {"第一条", "第二条"}


def test_experiment1_detects_missing_citation(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "law.txt").write_text("第一条　内容。\n\n第二条　内容。\n", encoding="utf-8")

    clause = ClauseAnswer(
        clause_id="c00",
        order=0,
        start_char=0,
        end_char=5,
        original_text="12345",
        clause_type="测试",
        risk=True,
        reasoning="test",
        legal_basis=["《劳动合同法》第九十九条"],  # 知识库里不存在
        legal_basis_verified_in_sources=False,
        pending_review_note="test only",
        annotated_by="tester",
        verification_status=VerificationStatus.PENDING_REVIEW,
        annotation_basis="unit test",
    )
    contract = ContractAnswer(
        sample_id="s1",
        sample_type=ContractSampleType.CLEAR_RISK,
        source="newly_designed",
        description="test",
        full_text="12345",
        clauses=[clause],
    )

    report = experiment1_knowledge_coverage([contract], kb_dir)
    assert report["required_citation_total"] == 1
    assert report["missing_count"] == 1
    assert "《劳动合同法》第九十九条" in report["missing"]


def test_experiment1_on_real_generated_answers_and_knowledge_base():
    """真实跑一次：50 份生成样本引用的法律依据，有多少能在当前
    data/knowledge/*.txt 里找到对应条号。这是本次任务要求的"实验1"的真实执行。
    """
    from config import settings

    answers = build_all_contracts()
    report = experiment1_knowledge_coverage(answers, settings.KNOWLEDGE_DIR)

    assert report["required_citation_total"] > 0
    # 本次 clause_bank.py 的设计原则是"只引用知识库里实际存在的条号"，
    # 所以这里要求覆盖率必须是 100%——如果不是，说明条款库引用了知识库里
    # 不存在的条号，是需要立即修的问题，不是可以接受的已知缺口。
    assert report["missing_count"] == 0, f"引用了知识库中不存在的法律依据：{report['missing']}"


def test_experiment6_rule_checker_recall_on_real_generated_samples():
    """真实跑一次：50 份样本里，规则层（真实 RuleChecker）相对标准答案标注的
    rule_expectation 的召回率和精确率。这是本次任务要求的"实验6"规则部分的
    真实执行（LLM 部分本沙箱无法运行，不在本测试范围内，见
    evaluation/diagnostics.py 模块说明）。
    """
    pairs = build_all_contracts_with_parts()
    report = experiment6_rule_layer_check(pairs)

    assert report["contracts_checked"] == 50
    assert report["total_expected_hits"] > 0
    # recall/precision 的具体数值记录在 docs/EVAL_BASELINE.md，这里只确认
    # 指标确实被算出来了（不是 None），且召回率不是 0（规则确实命中了一些）。
    assert report["recall"] is not None
    assert report["recall"] > 0


def test_experiment6_known_gap_date_range_probation_is_a_real_miss():
    """clause_bank.py::probation_duration_date_range 是刻意设计的"规则已知
    能力缺口"场景（合同期限用日期区间表达，正则提取不出月数；我们在
    rule_expectation 里主动标注了 expected_hit=False，因为这不是"规则本该
    测出来却坏了"，而是"规则设计时就没打算覆盖这种写法"）。

    这个测试确认：
    1) 这个已知缺口在真实 RuleChecker 面前确实表现为"没有命中"，不是我们
       凭空声称的——而且它被正确地归类到 known_limitation_gap，而不是
       missed（missed 应该只保留"预期能命中却没命中"的真正回归/bug）。
    2) clear_risk_12 这份合同（唯一一份用日期区间表达合同期限、
       ground_truth risk=True 但 expected_hit=False 的样本，见
       generate_contracts.py 的 _CLEAR_RISK_DOMINANT 列表第 12 项）确实
       出现在 known_limitation_gap 里，且**不**出现在 missed 里。
    """
    pairs = build_all_contracts_with_parts()
    report = experiment6_rule_layer_check(pairs)

    gap_sample_ids = {m["sample_id"] for m in report["known_limitation_gap"]}
    missed_sample_ids = {m["sample_id"] for m in report["missed"]}

    assert "clear_risk_12" in gap_sample_ids
    assert "clear_risk_12" not in missed_sample_ids
