"""条款素材库：一组参数化的"条款原型"，每个原型自带标准答案字段和
（如果适用）"规则层应不应该命中"的预期。50 份评估合同由
`evaluation/generate_contracts.py` 从这里挑选、传参、拼装而成，不是手写
50 份完整合同文本——这样每个样本的标准答案和条款原文是机械对应的，不会因为
手写时的疏漏导致两者不一致（对应 `evaluation/schemas.py` 里
`_check_clauses_cover_full_text_without_gap_or_overlap` 这类一致性校验，
生成器产出的数据应该天然满足，不依赖人工反复核对）。

**legal_basis 的可信度边界（如实说明）**：本文件引用的法条编号全部来自
`data/knowledge/劳动合同法.txt` 实际收录的条文（第几条、说的是什么事，和
`data/knowledge/SOURCES.md` 记录的条号一一对应，不是凭空编号）。但
SOURCES.md 同时说明：这些条文的**文本本身**本次没有逐字核对官方原文
（工具限制，见 SOURCES.md 开头说明）。所以这里产出的每条标准答案都会被
标记为 `legal_basis_verified_in_sources=True`（条号确实存在于知识库）但
`verification_status=candidate`（不是独立法律复核），没有一条是
"verified"——这不是疏漏，是如实反映本次任务的真实核验程度。

每个原型函数返回一个 dict：
    {
        "clause_type": str,
        "text": str,            # 条款正文（不含"第N条"编号，由生成器统一加标题）
        "title": str,           # 条款标题（如"试用期工资"），和生产代码
                                 # scripts/_samples.py 的习惯一致
        "answer": {...},        # 对应 ClauseAnswer 的字段（除 clause_id/order/
                                 # start_char/end_char/original_text，由生成器填）
        "rule_expectation": {"expected_hit": bool, "expected_rule_id": str|None},
    }
"""

from typing import Optional

ANNOTATED_BY = "claude-eval-generator-2026-10-10"  # 本次标注人：开发者/模型本身，不是独立法律复核人员


def _answer(
    *,
    risk: bool,
    reasoning: str,
    risk_type: Optional[str] = None,
    risk_level: Optional[str] = None,
    legal_basis: Optional[list[str]] = None,
    legal_basis_verified_in_sources: bool = False,
    basis_link_explanation: str = "",
    suggestion: str = "",
    context_dependent_condition: Optional[str] = None,
    acceptable_alternative_judgments: Optional[list[str]] = None,
    pending_review_note: Optional[str] = None,
    verification_status: str = "candidate",
    annotation_basis: str,
) -> dict:
    return dict(
        risk=risk,
        risk_type=risk_type if risk else None,
        risk_level=risk_level if risk else "none",
        reasoning=reasoning,
        legal_basis=legal_basis or [],
        legal_basis_verified_in_sources=legal_basis_verified_in_sources,
        basis_link_explanation=basis_link_explanation,
        suggestion=suggestion,
        context_dependent_condition=context_dependent_condition,
        acceptable_alternative_judgments=acceptable_alternative_judgments or [],
        pending_review_note=pending_review_note,
        annotated_by=ANNOTATED_BY,
        verification_status=verification_status,
        annotation_basis=annotation_basis,
    )


# ---------------------------------------------------------------------------
# 试用期工资（规则：rules/probation_salary.py，RULE_ID=probation_salary_below_80_percent）
# ---------------------------------------------------------------------------


def probation_salary(percent: int, probation_months: int = 3) -> dict:
    text = f"乙方试用期为{probation_months}个月，试用期工资为正式工资标准的百分之{_cn(percent)}。"
    is_risk = percent < 80
    answer = _answer(
        risk=is_risk,
        risk_type="试用期工资低于法定最低标准" if is_risk else None,
        risk_level="high" if is_risk else "none",
        reasoning=(
            f"试用期工资为正式工资标准的{percent}%，低于《劳动合同法》第二十条规定的80%下限。"
            if is_risk
            else f"试用期工资为正式工资标准的{percent}%，不低于《劳动合同法》第二十条规定的80%下限。"
        ),
        legal_basis=["《劳动合同法》第二十条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第二十条规定试用期工资不得低于本单位相同岗位最低档工资或劳动合同约定工资的80%，本条款约定的比例低于这个下限。" if is_risk else "本条款约定的比例不低于第二十条规定的下限，且规则还要求不低于当地最低工资标准，本样本未设置该限制条件，不在判断范围内。",
        suggestion=f"将试用期工资调整为不低于正式工资标准的80%。" if is_risk else "",
        acceptable_alternative_judgments=(
            ["如果当地最低工资标准高于本条约定金额，仍可能存在风险，需结合当地最低工资标准数值综合判断"]
            if not is_risk
            else []
        ),
        annotation_basis="rules/probation_salary.py 的判断标准 + 劳动合同法第二十条",
    )
    return {
        "clause_type": "试用期工资",
        "title": "试用期工资",
        "text": text,
        "answer": answer,
        "rule_expectation": {
            "expected_hit": is_risk,
            "expected_rule_id": "probation_salary_below_80_percent" if is_risk else None,
        },
    }


# ---------------------------------------------------------------------------
# 试用期期限（规则：rules/probation_duration.py，RULE_ID=probation_duration_exceeds_legal_cap）
# ---------------------------------------------------------------------------

_CONTRACT_TERM_LABEL = {
    "fixed_6m": ("本合同期限为六个月", "fixed_term", 6, 1),
    "fixed_1y": ("本合同期限为一年", "fixed_term", 12, 2),
    "fixed_2y": ("本合同期限为二年", "fixed_term", 24, 2),
    "fixed_3y": ("本合同期限为三年", "fixed_term", 36, 6),
    "non_fixed": ("本合同为无固定期限劳动合同", "non_fixed_term", None, 6),
    "task_based": ("本合同以完成软件开发项目为期限，任务完成之日合同终止", "task_based", None, 0),
}


def contract_term_and_probation(term_key: str, probation_months: Optional[int]) -> dict:
    """同时约定"合同期限"条款和"试用期期限"条款（这是真实合同常见写法——
    两件事往往在同一条或紧邻条款里一起约定），用于测试
    probation_duration 这条"跨条款"规则（它的 ReviewResult 用
    related_clause_ids 而不是单一 clause_id）。
    """
    term_text, contract_type, _, max_allowed = _CONTRACT_TERM_LABEL[term_key]

    if probation_months is None:
        text = f"{term_text}。乙方无需约定试用期。"
        is_risk = False
        rule_hit = False
    else:
        text = f"{term_text}。乙方试用期为{_cn(probation_months)}个月。"
        if contract_type == "task_based":
            is_risk = True
            reason = "本合同以完成一定工作任务为期限，依据《劳动合同法》第十九条第三款，不得约定试用期。"
        elif max_allowed == 0:
            is_risk = True
            reason = "依据《劳动合同法》第十九条，本合同类型不得约定试用期。"
        else:
            is_risk = probation_months > max_allowed
            reason = (
                f"{term_text}，依据《劳动合同法》第十九条，试用期最长不得超过{max_allowed}个月，"
                f"但约定了{probation_months}个月，超出法定上限。"
                if is_risk
                else f"{term_text}，约定试用期{probation_months}个月，未超过《劳动合同法》第十九条规定的{max_allowed}个月上限。"
            )
        rule_hit = is_risk

    answer = _answer(
        risk=is_risk,
        risk_type="试用期期限超过法定上限" if is_risk else None,
        risk_level="high" if is_risk else "none",
        reasoning=reason if probation_months is not None else "本条款未约定试用期，不涉及试用期期限风险。",
        legal_basis=["《劳动合同法》第十九条"] if probation_months is not None else [],
        legal_basis_verified_in_sources=True if probation_months is not None else False,
        basis_link_explanation="第十九条按合同期限分级规定了试用期上限，本条款的合同期限类型对应的上限已在判断理由中给出。" if probation_months is not None else "",
        suggestion=f"将试用期调整为不超过法定上限。" if is_risk else "",
        annotation_basis="rules/probation_duration.py 的判断标准 + 劳动合同法第十九条",
    )
    return {
        "clause_type": "合同期限与试用期",
        "title": "合同期限及试用期",
        "text": text,
        "answer": answer,
        "rule_expectation": {
            "expected_hit": rule_hit,
            "expected_rule_id": "probation_duration_exceeds_legal_cap" if rule_hit else None,
        },
    }


def probation_duration_date_range(probation_months: int) -> dict:
    """合同期限用日期区间表达（"自2024年1月1日起至2025年1月1日止"）——
    这是 rules/probation_duration.py 文档里明确写出的"不处理"的情况
    （需要算日期差，正则提取不出月数），刻意用来验证"规则漏检"这个已知
    边界，expected_hit 按真实法律判断应为 True，但 expected_rule_id 标注
    为 None，用于诊断实验 6 统计"规则漏检"。
    """
    text = (
        "本合同期限自2024年1月1日起至2024年7月1日止。"
        f"乙方试用期为{_cn(probation_months)}个月。"
    )
    # 2024-01-01 到 2024-07-01 是 6 个月的固定期限合同，法定试用期上限为 1 个月（3个月以上不满1年）
    is_risk = probation_months > 1
    answer = _answer(
        risk=is_risk,
        risk_type="试用期期限超过法定上限" if is_risk else None,
        risk_level="high" if is_risk else "none",
        reasoning=(
            f"合同期限为6个月（2024-01-01至2024-07-01），依据《劳动合同法》第十九条，"
            f"试用期最长不得超过1个月，但约定了{probation_months}个月，超出法定上限。"
            if is_risk
            else "合同期限为6个月，试用期未超过1个月上限。"
        ),
        legal_basis=["《劳动合同法》第十九条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="需要先计算日期区间得到合同期限长度，再套用第十九条的分级上限——这一步计算是本样本的设计重点。",
        suggestion="将试用期调整为不超过1个月。" if is_risk else "",
        pending_review_note=None,
        annotation_basis="合同期限用日期区间表达，需要人工/程序计算日期差才能得到月数，rules/probation_duration.py 当前的正则实现不支持这种表达（见该文件 docstring 明确声明的已知局限）",
    )
    return {
        "clause_type": "合同期限与试用期（日期区间表达）",
        "title": "合同期限及试用期",
        "text": text,
        "answer": answer,
        "rule_expectation": {
            # 故意设为 False：这是验证"规则会漏检"这个已知边界的样本，
            # 不是说这种情况不该被发现，而是现有规则实现确实检测不到。
            "expected_hit": False,
            "expected_rule_id": None,
        },
    }


# ---------------------------------------------------------------------------
# 竞业限制（第二十三、二十四条；当前规则集不处理，全部是 LLM-only 场景）
# ---------------------------------------------------------------------------


def noncompete(years: int, has_compensation: bool) -> dict:
    comp_text = "甲方按月给予乙方相当于离职前十二个月平均工资30%的经济补偿" if has_compensation else "甲方无需向乙方支付任何经济补偿"
    text = (
        f"乙方在劳动合同解除或者终止后{_cn(years)}年内，不得到与甲方有竞争关系的单位任职，{comp_text}。"
    )
    risk_reasons = []
    if years > 2:
        risk_reasons.append(f"竞业限制期限约定为{years}年，超过《劳动合同法》第二十四条规定的2年上限")
    if not has_compensation:
        risk_reasons.append("约定竞业限制但未约定经济补偿，不符合《劳动合同法》第二十三条关于竞业限制应给予经济补偿的规定")
    is_risk = bool(risk_reasons)
    answer = _answer(
        risk=is_risk,
        risk_type="竞业限制条款不合法" if is_risk else None,
        risk_level="high" if is_risk else "none",
        reasoning="；".join(risk_reasons) if risk_reasons else f"竞业限制期限{years}年未超过2年上限，且约定了经济补偿，符合第二十三、二十四条的基本要求。",
        legal_basis=["《劳动合同法》第二十三条", "《劳动合同法》第二十四条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第二十三条要求竞业限制应约定经济补偿，第二十四条规定竞业限制期限不得超过2年；本条款在这两点上的符合情况已在判断理由中说明。",
        suggestion="；".join(
            (["将竞业限制期限调整为不超过2年"] if years > 2 else [])
            + (["补充约定经济补偿标准"] if not has_compensation else [])
        ),
        context_dependent_condition="竞业限制条款的生效前提是该劳动者属于《劳动合同法》第二十四条规定的高级管理人员、高级技术人员或其他负有保密义务的人员——本样本未写明乙方岗位性质，假定满足此前提，如果乙方实际是普通岗位则竞业限制条款本身可能整体无效，需结合岗位信息判断",
        acceptable_alternative_judgments=["如果认为经济补偿标准（30%）过低也构成风险，这是本样本之外需要结合实际工资数额和当地标准判断的问题，标准答案未对补偿比例是否合理下结论"] if has_compensation else [],
        annotation_basis="劳动合同法第二十三、二十四条；当前项目规则集（rules/）未实现竞业限制相关规则，此样本只能检验 LLM/RAG 路径",
    )
    return {
        "clause_type": "竞业限制",
        "title": "竞业限制",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


# ---------------------------------------------------------------------------
# 必备条款缺失 / 完整的基线条款（第十七条）
# ---------------------------------------------------------------------------


def workplace_and_content(workplace: str = "上海市", role: str = "软件开发") -> dict:
    text = f"乙方在甲方从事{role}岗位工作，工作地点为{workplace}。"
    answer = _answer(
        risk=False,
        reasoning="工作内容和工作地点均已明确约定，符合《劳动合同法》第十七条关于必备条款的要求。",
        legal_basis=["《劳动合同法》第十七条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第十七条要求劳动合同必须具备工作内容和工作地点条款，本条款已满足。",
        annotation_basis="劳动合同法第十七条必备条款清单",
    )
    return {
        "clause_type": "工作内容和工作地点",
        "title": "工作内容和工作地点",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def unilateral_workplace_change() -> dict:
    text = "乙方工作地点为深圳市。甲方可以根据经营需要随时调整乙方工作地点，乙方应无条件服从。"
    answer = _answer(
        risk=True,
        risk_type="单方变更必备条款，可能排除劳动者协商权利",
        risk_level="medium",
        reasoning=(
            "工作地点属于《劳动合同法》第十七条规定的必备条款，变更劳动合同内容依据第三十五条"
            "应当由双方协商一致、采用书面形式；本条款约定甲方可单方随时调整且乙方必须无条件服从，"
            "实质上排除了劳动者的协商权利，可能被认定为《劳动合同法》第二十六条第一款第二项"
            "规定的'用人单位免除自己的法定责任、排除劳动者权利'的情形。"
        ),
        legal_basis=["《劳动合同法》第三十五条", "《劳动合同法》第二十六条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第三十五条要求变更合同内容需协商一致，第二十六条规定排除劳动者权利的约定无效；本条款的'无条件服从'表述与两条规定存在冲突。",
        suggestion="删除'无条件服从'的表述，改为'双方协商一致后方可调整工作地点，乙方有权要求就调整后的待遇等事项重新协商'。",
        context_dependent_condition=(
            "这类条款在实务中是否被认定无效，还取决于实际调整幅度是否'合理'（例如同城小范围调整"
            "通常被认为未超出用工自主权范围，跨城市大幅调整更可能被认定侵害劳动者权益）——"
            "本样本未写明实际调整场景，标准答案给出的是'条款约定本身'的风险判断，不是某次具体调整行为的判断"
        ),
        acceptable_alternative_judgments=[
            "如果认为这种格式条款在未实际发生调整前只是'潜在风险'，判定为 medium 而非 high，也是合理判断",
            "如果认为这类条款在实务中较为常见、实际执行时通常会协商，判定为 low 也有一定合理性——"
            "本样本标准答案选择 medium 作为折中，不代表 low/high 是错误判断",
        ],
        annotation_basis="劳动合同法第三十五条、第二十六条；这是一个法律界存在一定争议、高度依赖具体情境的问题，特意放入边界复杂类样本",
    )
    return {
        "clause_type": "工作地点单方变更",
        "title": "工作地点",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def missing_social_insurance_clause_contract_complete_otherwise() -> dict:
    """整份合同里刻意不出现"社会保险"条款（用于合同级"必备条款缺失"判断，
    这个判断发生在"合同整体"层面而不是某一条款内部，生成器会用它标记
    contract 级别的已知缺陷，不作为独立 clause 使用——保留在条款库里是
    为了文档记录这个设计点，当前未被 50 份合同选用，属于已知的后续扩展点。
    """
    raise NotImplementedError("合同级（非条款级）的标准答案不在本次 ClauseAnswer 的覆盖范围内，见函数说明")


# ---------------------------------------------------------------------------
# 工资支付 / 加班（第三十条、第八十五条）
# ---------------------------------------------------------------------------


def wage_payment_compliant(amount: int = 15000, pay_day: int = 10) -> dict:
    text = f"乙方正式工资为每月人民币{amount}元，甲方于次月{pay_day}日前足额支付。"
    answer = _answer(
        risk=False,
        reasoning="工资金额和支付时间均明确约定，符合《劳动合同法》第三十条关于及时足额支付劳动报酬的要求。",
        legal_basis=["《劳动合同法》第三十条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第三十条要求按约定和国家规定及时足额支付劳动报酬，本条款的约定满足这一要求的基本形式要件。",
        annotation_basis="劳动合同法第三十条",
    )
    return {
        "clause_type": "劳动报酬",
        "title": "劳动报酬",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def wage_payment_delay_no_liability(amount: int = 15000) -> dict:
    text = f"乙方正式工资为每月人民币{amount}元，甲方可以根据资金情况延迟支付，乙方不得因此追究甲方任何责任。"
    answer = _answer(
        risk=True,
        risk_type="约定免除拖欠工资责任",
        risk_level="high",
        reasoning=(
            "本条款约定用人单位可无限期延迟支付工资且劳动者不得追究责任，排除了劳动者依据"
            "《劳动合同法》第八十五条获得工资及加付赔偿金的权利，属于免除用人单位法定责任、"
            "排除劳动者权利的约定。"
        ),
        legal_basis=["《劳动合同法》第三十条", "《劳动合同法》第八十五条", "《劳动合同法》第二十六条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第三十条要求及时足额支付工资，第八十五条规定拖欠工资的加付赔偿金责任，第二十六条规定免除法定责任的约定无效；本条款试图约定免除这一责任。",
        suggestion="删除'不得因此追究甲方任何责任'的表述，按法定支付周期和金额约定工资支付。",
        annotation_basis="劳动合同法第三十条、第八十五条、第二十六条",
    )
    return {
        "clause_type": "劳动报酬",
        "title": "劳动报酬",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def work_hours_compliant() -> dict:
    text = "甲方安排乙方执行标准工时工作制度，每日工作八小时，每周工作五天，法定节假日依法安排乙方休息，如需加班，甲方应依法支付加班费。"
    answer = _answer(
        risk=False,
        reasoning="标准工时、法定节假日休息、依法支付加班费，未发现与工时相关的法律风险。",
        legal_basis=[],
        legal_basis_verified_in_sources=False,
        annotation_basis="标准工时制的常规合规表述，用作合规样本的基线条款",
    )
    return {
        "clause_type": "工作时间和休息休假",
        "title": "工作时间和休息休假",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def overtime_no_extra_pay() -> dict:
    text = "甲方可根据经营需要安排乙方加班，加班不另行支付加班费，已包含在乙方月工资内。"
    answer = _answer(
        risk=True,
        risk_type="加班费被一次性包入月工资，可能违反法定加班费支付标准",
        risk_level="medium",
        reasoning=(
            "《劳动合同法》第三十条要求及时足额支付劳动报酬，加班费有法定的加成支付标准"
            "（平时150%、休息日200%、法定节假日300%，依据《劳动法》相关规定），"
            "简单约定'已包含在月工资内'而不区分加班时长和加成比例，可能导致实际支付低于法定标准，"
            "但本条款本身没有给出具体工资数额和加班时长，无法直接计算是否真的低于法定标准。"
        ),
        legal_basis=["《劳动合同法》第三十条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第三十条是本知识库里与工资支付最直接相关的条文；加班费加成标准本身出自《劳动法》，本知识库未收录该法，见 SOURCES.md 的 pending_source 记录，这里的法律依据只能到第三十条的一般性要求，不能引用具体加成比例的条文。",
        suggestion="明确加班费按法定标准（平时150%、休息日200%、法定节假日300%）另行计算，不与月工资笼统合并。",
        context_dependent_condition="是否真的违法取决于乙方的实际加班时长和月工资数额是否足以覆盖法定加班费——本条款未提供这两个数值，无法下绝对结论，只能指出条款表述本身存在的合规风险",
        pending_review_note="加班费法定加成标准出自《劳动法》第四十四条，本知识库当前未收录《劳动法》（见 SOURCES.md），这里引用的只是《劳动合同法》第三十条的一般性要求，法律依据链条不完整，建议人工补充核验",
        verification_status="pending_review",
        annotation_basis="劳动合同法第三十条 + 常识性加班费加成标准（后者未在本知识库核验，见 pending_review_note）",
    )
    return {
        "clause_type": "工作时间和休息休假",
        "title": "工作时间和休息休假",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


# ---------------------------------------------------------------------------
# 服务期培训违约金（第二十二条）、一般违约金限制（第二十五条）
# ---------------------------------------------------------------------------


def service_period_penalty(training_cost: int, penalty: int, service_months: int, elapsed_months: int) -> dict:
    remaining_months = max(service_months - elapsed_months, 0)
    max_allowed_penalty = round(training_cost * remaining_months / service_months) if service_months else 0
    is_risk = penalty > max_allowed_penalty
    text = (
        f"甲方为乙方提供专项培训，培训费用为人民币{training_cost}元，双方约定服务期{service_months}个月。"
        f"乙方提前离职违反服务期约定的，应向甲方支付违约金人民币{penalty}元。"
    )
    answer = _answer(
        risk=is_risk,
        risk_type="服务期违约金超过法定上限" if is_risk else None,
        risk_level="high" if is_risk else "none",
        reasoning=(
            f"依据《劳动合同法》第二十二条，违约金不得超过服务期尚未履行部分所应分摊的培训费用。"
            f"本条款未结合实际离职时间分摊计算，直接约定固定违约金{penalty}元，"
            f"如果乙方在服务期履行较多后离职，按分摊计算的违约金应远低于{penalty}元，"
            f"固定金额的约定存在超过法定上限的风险。"
            if is_risk
            else f"违约金{penalty}元未超过培训费用{training_cost}元本身，但第二十二条要求的是'按尚未履行部分分摊'，"
            f"本条款约定的是固定金额，不是分摊计算方式，仍需结合实际离职时间判断是否超限。"
        ),
        legal_basis=["《劳动合同法》第二十二条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第二十二条明确违约金上限为培训费用，且用人单位要求的违约金不得超过服务期尚未履行部分所分摊的培训费用。",
        suggestion="将违约金条款改为按服务期尚未履行部分比例分摊培训费用计算，不约定固定金额。",
        context_dependent_condition="实际应支付的违约金数额取决于乙方实际离职时点——本条款约定的固定金额本身就与'分摊计算'的法定方式不符，这是条款设计层面的风险，不是某次具体离职场景的计算错误",
        annotation_basis="劳动合同法第二十二条",
    )
    return {
        "clause_type": "服务期与培训违约金",
        "title": "培训与服务期",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def general_liquidated_damages() -> dict:
    text = "乙方违反本合同任何约定的，应向甲方支付违约金人民币20000元。"
    answer = _answer(
        risk=True,
        risk_type="超出法定情形约定劳动者违约金",
        risk_level="high",
        reasoning=(
            "《劳动合同法》第二十五条规定，除第二十二条（服务期）和第二十三条（竞业限制）"
            "规定的情形外，用人单位不得与劳动者约定由劳动者承担违约金。本条款约定'违反任何约定'"
            "都需支付违约金，远超这两种法定情形，属于违法约定。"
        ),
        legal_basis=["《劳动合同法》第二十五条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第二十五条是本条款风险的直接依据，明确限定了劳动者违约金的两种合法情形。",
        suggestion="删除本条款，或改为仅在服务期、竞业限制两种法定情形下约定违约金。",
        annotation_basis="劳动合同法第二十五条",
    )
    return {
        "clause_type": "违约责任",
        "title": "违约责任",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


# ---------------------------------------------------------------------------
# 社会保险（强制缴纳，不可协商放弃）
# ---------------------------------------------------------------------------


def social_insurance_compliant() -> dict:
    text = "甲方依法为乙方缴纳社会保险，具体险种和缴纳比例按国家及地方规定执行。"
    answer = _answer(
        risk=False,
        reasoning="依法缴纳社会保险，符合《劳动合同法》第十七条关于社会保险属于必备条款的要求。",
        legal_basis=["《劳动合同法》第十七条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第十七条将社会保险列为劳动合同必备条款之一，本条款已满足。",
        annotation_basis="劳动合同法第十七条",
    )
    return {
        "clause_type": "社会保险",
        "title": "社会保险",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def social_insurance_waiver_with_cash() -> dict:
    text = "经双方协商一致，乙方自愿放弃由甲方缴纳社会保险，甲方每月向乙方支付人民币800元作为补偿。"
    answer = _answer(
        risk=True,
        risk_type="以协商放弃社会保险违反强制性规定",
        risk_level="high",
        reasoning=(
            "缴纳社会保险是法律强制性规定，不属于用人单位和劳动者可以自由协商放弃的事项，"
            "即使双方'自愿协商一致'并给予现金补偿，该约定仍因违反法律、行政法规的强制性规定"
            "而无效（《劳动合同法》第二十六条第一款第三项）。"
        ),
        legal_basis=["《劳动合同法》第十七条", "《劳动合同法》第二十六条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第十七条将社会保险列为必备条款，第二十六条规定违反强制性规定的约定无效；本条款试图用协商方式规避这一强制性义务。",
        suggestion="删除本条款，依法为乙方缴纳社会保险，不得以现金补偿替代。",
        acceptable_alternative_judgments=["社保具体由哪个条款/规则识别出来，可能需要结合实际社保缴纳记录核实，但条款本身的法律效力判断不受此影响"],
        annotation_basis="劳动合同法第十七条、第二十六条；社保强制缴纳是劳动法领域的常识性规则",
    )
    return {
        "clause_type": "社会保险",
        "title": "社会保险",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


# ---------------------------------------------------------------------------
# 违法解除/终止、经济补偿（第四十六、四十七、四十八、八十七条）
# ---------------------------------------------------------------------------


def illegal_termination_no_compensation() -> dict:
    text = "甲方可随时无理由解除本合同，无需提前通知，亦无需向乙方支付任何经济补偿或赔偿金。"
    answer = _answer(
        risk=True,
        risk_type="约定用人单位无理由解除且不承担法定补偿/赔偿责任",
        risk_level="high",
        reasoning=(
            "用人单位解除劳动合同必须符合《劳动合同法》规定的法定情形（如第三十九、四十条），"
            "并在相应情形下依据第四十六、四十七条支付经济补偿；违法解除的，依据第四十八、"
            "八十七条还应支付二倍经济补偿的赔偿金。本条款约定甲方可'随时无理由解除'且"
            "'无需支付任何补偿或赔偿'，直接排除了劳动者依法应获得的经济补偿和赔偿金权利。"
        ),
        legal_basis=[
            "《劳动合同法》第四十六条",
            "《劳动合同法》第四十七条",
            "《劳动合同法》第四十八条",
            "《劳动合同法》第八十七条",
        ],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第四十六、四十七条规定应支付经济补偿的情形和计算标准，第四十八、八十七条规定违法解除的赔偿金标准；本条款试图一次性排除全部这些法定责任。",
        suggestion="删除本条款，解除合同应依据法定情形并按规定支付经济补偿或赔偿金。",
        annotation_basis="劳动合同法第四十六、四十七、四十八、八十七条",
    )
    return {
        "clause_type": "合同解除",
        "title": "合同解除",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def termination_compliant() -> dict:
    text = (
        "本合同解除或终止的，双方应依照《中华人民共和国劳动合同法》的规定办理，"
        "甲方应在解除或终止劳动合同时出具解除或终止劳动合同的证明，并在十五日内为乙方办理档案和社会保险关系转移手续。"
    )
    answer = _answer(
        risk=False,
        reasoning="解除/终止条款按法律规定办理，未发现排除法定责任或权利的表述。",
        legal_basis=[],
        legal_basis_verified_in_sources=False,
        annotation_basis="常规合规表述，用作合规样本的基线条款",
    )
    return {
        "clause_type": "合同解除",
        "title": "合同解除",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


# ---------------------------------------------------------------------------
# 保密、争议解决、违约责任等基线合规条款（没有法律风险，用于补足"正常条款"占比）
# ---------------------------------------------------------------------------


def confidentiality_compliant() -> dict:
    text = "乙方应对在职期间知悉的甲方商业秘密予以保密，离职后仍应继续履行保密义务，保密范围和期限双方另行约定。"
    answer = _answer(
        risk=False,
        reasoning="保密义务约定本身不违反强制性规定，未发现风险。",
        annotation_basis="常规保密条款，用作合规样本的基线条款",
    )
    return {
        "clause_type": "保密义务",
        "title": "保密义务",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def dispute_resolution_compliant() -> dict:
    text = "因履行本合同发生争议的，双方应协商解决；协商不成的，可以向劳动争议仲裁委员会申请仲裁。"
    answer = _answer(
        risk=False,
        reasoning="争议解决条款符合劳动争议处理的法定途径（先协商、后仲裁），未排除法定仲裁/诉讼权利。",
        annotation_basis="常规争议解决条款，用作合规样本的基线条款",
    )
    return {
        "clause_type": "争议解决",
        "title": "争议解决",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def general_breach_liability_compliant() -> dict:
    text = "任何一方违反本合同约定，应当承担相应的违约责任并赔偿由此造成的损失。"
    answer = _answer(
        risk=False,
        reasoning="双向、对等的一般性违约责任约定，不是针对劳动者单方的违约金条款，不违反第二十五条的限制。",
        legal_basis=["《劳动合同法》第二十五条"],
        legal_basis_verified_in_sources=True,
        basis_link_explanation="第二十五条限制的是用人单位单方约定由劳动者承担违约金，本条款是双向对等责任，不属于该限制范围。",
        acceptable_alternative_judgments=["如果结合其他条款发现实际只对乙方单方适用，判断可能需要调整——本条款独立看是合规的"],
        annotation_basis="劳动合同法第二十五条（反向确认：本条款不落入该条限制范围）",
    )
    return {
        "clause_type": "违约责任",
        "title": "违约责任",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


def insufficient_context_probation_salary_unspecified() -> dict:
    """标准答案无法确定的样本：试用期工资"另行约定"，没有给出具体比例，
    真实审查时既不能断定合规也不能断定违规，必须结合实际发放数额判断。
    """
    text = "乙方试用期工资由双方另行约定，具体数额见薪酬确认单（本合同未附）。"
    answer = _answer(
        risk=False,
        reasoning="条款未给出具体试用期工资比例或数额，无法依据第二十条的80%标准做出判断。",
        risk_level="none",
        pending_review_note="缺少具体工资数额，无法判断是否符合《劳动合同法》第二十条的80%下限，需要补充薪酬确认单内容后才能判断，建议人工核实后补充标准答案",
        context_dependent_condition="必须结合另附的'薪酬确认单'实际数额才能判断是否合规——本合同样本未提供该文件内容，这是刻意设计的'证据不足'场景",
        verification_status="pending_review",
        annotation_basis="刻意设计的信息不足场景，用于检验系统（以及 LLM）在证据不足时是否会过度确定地下结论，而不是去如实说明依据不足",
    )
    return {
        "clause_type": "试用期工资",
        "title": "试用期工资",
        "text": text,
        "answer": answer,
        "rule_expectation": {"expected_hit": False, "expected_rule_id": None},
    }


_CN_NUM = {0: "零", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}


def _cn(n: int) -> str:
    """把 0~99 的整数转成常见的中文数字写法（够用即可，不追求覆盖所有写法，
    和 rules/probation_salary.py::_cn_percent_to_int 的反向转换覆盖范围一致）。
    """
    if n in _CN_NUM:
        return _CN_NUM[n]
    if n < 20:
        return "十" + _CN_NUM[n - 10]
    tens, units = divmod(n, 10)
    s = _CN_NUM[tens] + "十"
    if units:
        s += _CN_NUM[units]
    return s


# 公开别名：供 evaluation/generate_contracts.py 给合同生成"第N条"标题用，
# 不直接伸手用带下划线的"私有"名字。
to_cn_number = _cn
