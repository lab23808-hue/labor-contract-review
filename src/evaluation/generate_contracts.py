"""50 份评估合同生成器：从 `evaluation/clause_bank.py` 的条款原型拼装出完整
合同文本 + 每份合同的标准答案（`evaluation/schemas.py::ContractAnswer`）。

不手写 50 份完整合同——那样标准答案和合同原文的一致性完全依赖人工反复核对，
容易出错。这里用"配方"（recipe：选哪些条款原型、给什么参数）描述每份合同，
拼装过程本身保证切分边界、clause_id、原文三者互相一致（`ContractAnswer`
的 pydantic 校验器会在写文件前再确认一遍，见 `build_contract`）。

运行：
    python scripts/generate_eval_contracts.py
会把 50 份合同的 .txt 原文写到 data/eval_samples/contracts/，标准答案 JSON
写到 data/eval_samples/answers/，另外写一份 manifest.json（每份合同的类型/
来源/条款数/风险条款数统计）和 rule_expectations.json（给诊断实验 6 用，
不是标准答案 schema 的一部分，见 clause_bank.py 顶部说明）。
"""

import json
from pathlib import Path

from evaluation import clause_bank as cb
from evaluation.schemas import ClauseAnswer, ContractAnswer, ContractSampleType

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "eval_samples"
CONTRACTS_DIR = DATA_DIR / "contracts"
ANSWERS_DIR = DATA_DIR / "answers"


def _cn_ordinal(n: int) -> str:
    return cb.to_cn_number(n)


def build_contract(
    sample_id: str,
    sample_type: ContractSampleType,
    source: str,
    description: str,
    parts: list[dict],
    contract_version: str = "v1",
) -> ContractAnswer:
    blocks = []
    clauses = []
    offset = 0
    for i, part in enumerate(parts):
        heading = f"第{_cn_ordinal(i + 1)}条 {part['title']}"
        block_text = f"{heading}\n{part['text']}"
        blocks.append(block_text)

        clause_id = f"{sample_id}_c{i:02d}"
        start_char = offset
        end_char = offset + len(block_text)

        answer_kwargs = dict(part["answer"])
        clauses.append(
            ClauseAnswer(
                clause_id=clause_id,
                order=i,
                start_char=start_char,
                end_char=end_char,
                original_text=block_text,
                clause_type=part["clause_type"],
                **answer_kwargs,
            )
        )
        offset = end_char + 2  # 两个块之间用 "\n\n" 连接，offset 要跳过这两个字符

    full_text = "\n\n".join(blocks)

    return ContractAnswer(
        sample_id=sample_id,
        contract_version=contract_version,
        sample_type=sample_type,
        source=source,
        description=description,
        full_text=full_text,
        clauses=clauses,
    )


def _baseline_fillers() -> list[dict]:
    """每份合同都会用到的"正常条款"基线集合，保证"必须保留正常条款的标准
    答案，不能只标记风险条款"这一要求——不是每份合同都用全部，按需挑选。
    """
    return [
        cb.workplace_and_content(),
        cb.wage_payment_compliant(),
        cb.work_hours_compliant(),
        cb.social_insurance_compliant(),
        cb.confidentiality_compliant(),
        cb.dispute_resolution_compliant(),
        cb.general_breach_liability_compliant(),
        cb.termination_compliant(),
    ]


# ---------------------------------------------------------------------------
# 20 份"明确存在风险"的合同：每份一个主导风险条款原型 + 若干基线正常条款
# （用于测量漏检：如果系统连这些单一、明确的风险都测不出来，说明漏检严重）
# ---------------------------------------------------------------------------

_CLEAR_RISK_DOMINANT = [
    lambda: cb.probation_salary(50),
    lambda: cb.probation_salary(40),
    lambda: cb.probation_salary(60),
    lambda: cb.probation_salary(70),
    lambda: cb.probation_salary(75),
    lambda: cb.probation_salary(0),
    lambda: cb.contract_term_and_probation("fixed_1y", 3),
    lambda: cb.contract_term_and_probation("fixed_6m", 2),
    lambda: cb.contract_term_and_probation("non_fixed", 7),
    lambda: cb.contract_term_and_probation("task_based", 1),
    lambda: cb.contract_term_and_probation("fixed_3y", 7),
    lambda: cb.probation_duration_date_range(3),
    lambda: cb.noncompete(3, True),
    lambda: cb.noncompete(2, False),
    lambda: cb.noncompete(4, False),
    lambda: cb.wage_payment_delay_no_liability(),
    lambda: cb.service_period_penalty(training_cost=10000, penalty=10000, service_months=24, elapsed_months=20),
    lambda: cb.general_liquidated_damages(),
    lambda: cb.social_insurance_waiver_with_cash(),
    lambda: cb.illegal_termination_no_compensation(),
]


def _build_clear_risk_contracts() -> list[tuple[ContractAnswer, list[dict]]]:
    out = []
    fillers = _baseline_fillers()
    for i, make_dominant in enumerate(_CLEAR_RISK_DOMINANT):
        dominant = make_dominant()
        # 每份合同固定选 4 条基线正常条款（轮换起点，避免 50 份合同里基线条款
        # 的顺序/组合完全重复），加 1 条主导风险条款，共 5 条。
        picked_fillers = [fillers[(i + j) % len(fillers)] for j in range(4)]
        parts = picked_fillers[:2] + [dominant] + picked_fillers[2:]
        contract = build_contract(
            sample_id=f"clear_risk_{i + 1:02d}",
            sample_type=ContractSampleType.CLEAR_RISK,
            source="newly_designed",
            description=f"以「{dominant['clause_type']}」为主导的明确风险样本，用于测量漏检。",
            parts=parts,
        )
        out.append((contract, parts))
    return out


# ---------------------------------------------------------------------------
# 10 份"基本合规"的合同：全部基线合规条款 + 个别恰好合规的边界值
# （用于测量误报：系统不应该在这些样本上报出风险）
# ---------------------------------------------------------------------------

_COMPLIANT_EXTRA = [
    lambda: cb.probation_salary(80),
    lambda: cb.probation_salary(85),
    lambda: cb.probation_salary(100),
    lambda: cb.contract_term_and_probation("fixed_1y", 2),
    lambda: cb.contract_term_and_probation("non_fixed", 6),
    lambda: cb.contract_term_and_probation("fixed_3y", 6),
    lambda: cb.noncompete(2, True),
    lambda: cb.noncompete(1, True),
    lambda: cb.service_period_penalty(training_cost=12000, penalty=1000, service_months=24, elapsed_months=20),
    lambda: cb.contract_term_and_probation("fixed_6m", None),
]


def _build_basically_compliant_contracts() -> list[tuple[ContractAnswer, list[dict]]]:
    out = []
    fillers = _baseline_fillers()
    for i, make_extra in enumerate(_COMPLIANT_EXTRA):
        extra = make_extra()
        picked_fillers = [fillers[(i * 3 + j) % len(fillers)] for j in range(len(fillers))]
        parts = picked_fillers + [extra]
        contract = build_contract(
            sample_id=f"compliant_{i + 1:02d}",
            sample_type=ContractSampleType.BASICALLY_COMPLIANT,
            source="newly_designed",
            description="全部基线合规条款 + 一条恰好处于合规边界的条款，用于测量误报。",
            parts=parts,
        )
        out.append((contract, parts))
    return out


# ---------------------------------------------------------------------------
# 10 份"同时包含风险和合规条款"的混合合同（最接近真实合同的样本）
# ---------------------------------------------------------------------------

_MIXED_RISK_PAIRS = [
    (lambda: cb.probation_salary(55), lambda: cb.overtime_no_extra_pay()),
    (lambda: cb.contract_term_and_probation("fixed_1y", 3), lambda: cb.general_liquidated_damages()),
    (lambda: cb.noncompete(3, False), lambda: cb.wage_payment_delay_no_liability()),
    (lambda: cb.social_insurance_waiver_with_cash(), lambda: cb.probation_salary(45)),
    (lambda: cb.illegal_termination_no_compensation(), lambda: cb.contract_term_and_probation("non_fixed", 8)),
    (lambda: cb.service_period_penalty(8000, 8000, 12, 2), lambda: cb.noncompete(2, False)),
    (lambda: cb.unilateral_workplace_change(), lambda: cb.probation_salary(65)),
    (lambda: cb.general_liquidated_damages(), lambda: cb.contract_term_and_probation("task_based", 2)),
    (lambda: cb.probation_duration_date_range(2), lambda: cb.wage_payment_delay_no_liability()),
    (lambda: cb.overtime_no_extra_pay(), lambda: cb.social_insurance_waiver_with_cash()),
]


def _build_mixed_contracts() -> list[tuple[ContractAnswer, list[dict]]]:
    out = []
    fillers = _baseline_fillers()
    for i, (make_a, make_b) in enumerate(_MIXED_RISK_PAIRS):
        a, b = make_a(), make_b()
        picked_fillers = [fillers[(i + j) % len(fillers)] for j in range(5)]
        parts = picked_fillers[:2] + [a] + picked_fillers[2:4] + [b] + picked_fillers[4:]
        contract = build_contract(
            sample_id=f"mixed_{i + 1:02d}",
            sample_type=ContractSampleType.MIXED,
            source="newly_designed",
            description=f"同时包含两处风险（{a['clause_type']}、{b['clause_type']}）和多条正常条款的混合样本。",
            parts=parts,
        )
        out.append((contract, parts))
    return out


# ---------------------------------------------------------------------------
# 10 份"边界、复杂及组合场景"合同
# ---------------------------------------------------------------------------

_BOUNDARY_SETS = [
    [cb.probation_salary(80), cb.contract_term_and_probation("fixed_1y", 2)],
    [cb.unilateral_workplace_change()],
    [cb.overtime_no_extra_pay()],
    [cb.insufficient_context_probation_salary_unspecified()],
    [cb.probation_salary(81), cb.noncompete(2, True)],
    [cb.contract_term_and_probation("non_fixed", 6), cb.service_period_penalty(6000, 6000, 12, 11)],
    [cb.contract_term_and_probation("fixed_2y", 2)],
    [cb.unilateral_workplace_change(), cb.overtime_no_extra_pay()],
    [cb.insufficient_context_probation_salary_unspecified(), cb.noncompete(2, True)],
    [cb.probation_duration_date_range(1)],
]

_BOUNDARY_DESCRIPTIONS = [
    "试用期工资恰好 80% 下限 + 试用期恰好等于法定上限，两处均为合规边界值。",
    "工作地点单方变更条款：法律界存在争议、高度依赖具体情境的边界场景。",
    "加班费笼统包入月工资：缺少具体数额，无法直接计算是否违法的边界场景。",
    "试用期工资另行约定但未给出数额：标准答案本身也标记为 pending_review 的信息不足场景。",
    "试用期工资恰好略高于 80% 下限 + 竞业限制合规，组合判断合规样本的边界场景。",
    "无固定期限合同恰好 6 个月试用期上限 + 服务期违约金在履行将满时的临界计算场景。",
    "二年固定期限合同恰好 2 个月试用期上限，合规边界场景。",
    "工作地点单方变更 + 加班费包入月工资，两处均为需结合上下文判断的组合场景。",
    "信息不足的试用期工资条款 + 竞业限制合规条款组合，用于检验系统是否会在信息不足处也给出过度确定的结论。",
    "合同期限用日期区间表达且试用期恰好不超过上限，验证规则对日期区间的处理能力（已知局限，见 clause_bank.py）。",
]


def _build_boundary_contracts() -> list[tuple[ContractAnswer, list[dict]]]:
    out = []
    fillers = _baseline_fillers()
    for i, (extra_parts, desc) in enumerate(zip(_BOUNDARY_SETS, _BOUNDARY_DESCRIPTIONS)):
        picked_fillers = [fillers[(i + j) % len(fillers)] for j in range(4)]
        parts = picked_fillers[:2] + list(extra_parts) + picked_fillers[2:]
        contract = build_contract(
            sample_id=f"boundary_{i + 1:02d}",
            sample_type=ContractSampleType.BOUNDARY_COMPLEX,
            source="newly_designed",
            description=desc,
            parts=parts,
        )
        out.append((contract, parts))
    return out


def build_all_contracts_with_parts() -> list[tuple[ContractAnswer, list[dict]]]:
    """返回 (ContractAnswer, parts) 对——parts 保留了每个条款原型的
    `rule_expectation`，供 `write_all()` 产出 rule_expectations.json。
    """
    pairs = (
        _build_clear_risk_contracts()
        + _build_basically_compliant_contracts()
        + _build_mixed_contracts()
        + _build_boundary_contracts()
    )
    ids = [c.sample_id for c, _ in pairs]
    assert len(ids) == len(set(ids)), "sample_id 必须唯一"
    return pairs


def build_all_contracts() -> list[ContractAnswer]:
    """只要 ContractAnswer 列表时用这个（例如测试里校验 schema）。"""
    return [contract for contract, _ in build_all_contracts_with_parts()]


def _rule_expectations_for(contract: ContractAnswer, parts: list[dict]) -> dict:
    """记录这份合同每个条款"规则层应不应该命中"的预期，供诊断实验 6 使用。
    不属于标准答案 schema（见 clause_bank.py 顶部说明），单独存一份文件。
    """
    return {clause.clause_id: part["rule_expectation"] for clause, part in zip(contract.clauses, parts)}


def write_all(output_dir: Path = DATA_DIR) -> dict:
    contracts_dir = output_dir / "contracts"
    answers_dir = output_dir / "answers"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    answers_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"samples": [], "distribution": {}, "generator": "evaluation/generate_contracts.py"}
    rule_expectations: dict = {}

    for contract, parts in build_all_contracts_with_parts():
        (contracts_dir / f"{contract.sample_id}.txt").write_text(contract.full_text, encoding="utf-8")
        (answers_dir / f"{contract.sample_id}.json").write_text(
            contract.model_dump_json(indent=2), encoding="utf-8"
        )
        rule_expectations[contract.sample_id] = _rule_expectations_for(contract, parts)

        manifest["samples"].append(
            {
                "sample_id": contract.sample_id,
                "sample_type": contract.sample_type.value,
                "source": contract.source,
                "clause_count": len(contract.clauses),
                "risk_clause_count": contract.risk_clause_count,
                "compliant_clause_count": contract.compliant_clause_count,
                "description": contract.description,
            }
        )

    for sample in manifest["samples"]:
        manifest["distribution"][sample["sample_type"]] = manifest["distribution"].get(sample["sample_type"], 0) + 1

    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "rule_expectations.json").write_text(
        json.dumps(rule_expectations, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return manifest


if __name__ == "__main__":
    manifest = write_all()
    print(f"已生成 {len(manifest['samples'])} 份评估合同到 {DATA_DIR}")
    print("分布：", manifest["distribution"])
