"""probation_duration_rule：试用期长度是否超过《劳动合同法》第十九条规定的上限。

数据来源：合同期限和试用期都需要从条款原文里用正则提取，只在本文件内部使用，
不对外暴露、不被其他规则共用——每条规则只提取自己需要的数据，不存在一个所有
规则都要先经过的统一事实层。

只用正则，覆盖范围有限，是刻意的权衡：
    - 能处理：“本合同期限为一年”“合同期限3年”“无固定期限”
             “试用期为三个月”“试用期2个月”
    - 不处理：用日期区间表达的合同期限（比如“自2024年1月1日起至2025年1月1日
      止”，需要算日期差）
    - 中文数字只识别一到十二，不处理“二十”“三十”这类更复杂的表达
提取不到合同期限或试用期，就跳过这条规则的检查，不猜测、不用默认值补全。

这是一条跨条款问题（同时涉及“合同期限”条款和“试用期”条款），所以产出的
ReviewResult 用 clause_id=None + related_clause_ids 指向两条原文条款，
不指向单一条款——这和 mandatory_clauses 类问题（完全没有对应条款）不同，
也和 probation_salary 这种单条款内问题（有明确的 clause_id）不同。
"""

import re
from enum import Enum
from typing import NamedTuple, Optional

from core import Clause, ReviewResult, ReviewSource, RiskLevel

RULE_ID = "probation_duration_exceeds_legal_cap"
LEGAL_BASIS = "《劳动合同法》第十九条"


class _ContractType(str, Enum):
    FIXED_TERM = "fixed_term"
    NON_FIXED_TERM = "non_fixed_term"
    TASK_BASED = "task_based"


_TYPE_LABELS = {
    _ContractType.FIXED_TERM: "固定期限劳动合同",
    _ContractType.NON_FIXED_TERM: "无固定期限劳动合同",
    _ContractType.TASK_BASED: "以完成一定工作任务为期限的劳动合同",
}

_CN_NUMBER_MAP = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}
_NUMBER_TOKEN = r"(?:十一|十二|\d{1,3}|[一二三四五六七八九十两])"

_TASK_BASED_RE = re.compile(r"以完成一定[的]?工作任务为期限")
_NON_FIXED_TERM_RE = re.compile(r"无固定期限")
_FIXED_DURATION_RE = re.compile(
    rf"(?:劳动)?合同期限[^0-9一二三四五六七八九十两]{{0,6}}(?P<num>{_NUMBER_TOKEN})\s*(?P<unit>个月|月|年)"
)
_PROBATION_RE = re.compile(
    rf"试用期[^0-9一二三四五六七八九十两]{{0,6}}(?P<num>{_NUMBER_TOKEN})\s*(?P<unit>个月|月|年)"
)


class _Duration(NamedTuple):
    contract_type: _ContractType
    months: Optional[int]  # 仅 FIXED_TERM 时有意义，其余类型恒为 None


def _parse_number(token: str) -> Optional[int]:
    if token.isdigit():
        return int(token)
    return _CN_NUMBER_MAP.get(token)


def _to_months(number: int, unit: str) -> int:
    return number * 12 if unit == "年" else number


def _extract_duration(text: str) -> Optional[_Duration]:
    if _TASK_BASED_RE.search(text):
        return _Duration(_ContractType.TASK_BASED, None)
    if _NON_FIXED_TERM_RE.search(text):
        return _Duration(_ContractType.NON_FIXED_TERM, None)
    match = _FIXED_DURATION_RE.search(text)
    if not match:
        return None
    number = _parse_number(match.group("num"))
    if number is None:
        return None
    return _Duration(_ContractType.FIXED_TERM, _to_months(number, match.group("unit")))


def _extract_probation_months(text: str) -> Optional[int]:
    match = _PROBATION_RE.search(text)
    if not match:
        return None
    number = _parse_number(match.group("num"))
    if number is None:
        return None
    return _to_months(number, match.group("unit"))


def _max_allowed_probation_months(duration: _Duration) -> Optional[int]:
    """该合同类型允许的最长试用期（月）；None 表示依法不得约定试用期。"""
    if duration.contract_type == _ContractType.TASK_BASED:
        return None
    if duration.contract_type == _ContractType.NON_FIXED_TERM:
        return 6
    months = duration.months
    if months is None:
        return None  # 防御性处理：FIXED_TERM 理论上必有 months
    if months < 3:
        return None
    if months < 12:
        return 1
    if months < 36:
        return 2
    return 6


def _duration_label(duration: _Duration) -> str:
    if duration.contract_type == _ContractType.FIXED_TERM:
        return f"合同期限为{duration.months}个月"
    return f"合同为{_TYPE_LABELS[duration.contract_type]}"


def check_probation_duration(clauses: list[Clause]) -> list[ReviewResult]:
    """提取合同期限和试用期，判断试用期是否超过法定上限。

    需要同时提取到合同期限和试用期信息才会判断；任一提取不到就跳过（返回
    空列表），不用默认值补全缺失信息。

    配对策略分两步，不是简单地"分别取条款列表里第一次能提取到的值"：

    1. 优先寻找**同一条款内**同时能提取出合同期限和试用期月数的情况——这是
       真实合同最常见的写法（"本合同期限为一年，乙方试用期为二个月"这种期限
       和试用期写在一起的条款），同条款内的配对不存在"张冠李戴"的风险，一旦
       找到就直接采用，不再看其它条款。
    2. 只有当**没有任何一条**条款同时具备两者时，才退回旧的逐条款独立扫描：
       合同期限和试用期月数分别取各自在条款列表里第一次出现的值。

    这是为了修复一个真实误报：如果直接对"合同
    期限"和"试用期月数"各自独立取"第一次出现的值"，当某条和期限无关的条款
    （比如"试用期工资"条款，原文里恰好也复述了一次试用期月数作为上下文）比
    真正描述合同期限的条款更早出现时，就会把两个不该配对的数字错误地凑成
    一对，产出误报。第2步的退回逻辑仍然可能有同样的理论局限（这是本规则
    v1 的已知边界，不是本次修复要彻底解决的问题），但至少在"期限和试用期
    写在同一条款里"这个最常见的场景下不会再误判。
    """
    duration: Optional[_Duration] = None
    duration_clause_id: Optional[str] = None
    probation_months: Optional[int] = None
    probation_clause_id: Optional[str] = None

    for clause in clauses:
        found_duration = _extract_duration(clause.original_text)
        found_probation = _extract_probation_months(clause.original_text)
        if found_duration is not None and found_probation is not None:
            duration = found_duration
            duration_clause_id = clause.clause_id
            probation_months = found_probation
            probation_clause_id = clause.clause_id
            break

    if duration is None or probation_months is None:
        for clause in clauses:
            if duration is None:
                found = _extract_duration(clause.original_text)
                if found is not None:
                    duration = found
                    duration_clause_id = clause.clause_id
            if probation_months is None:
                months = _extract_probation_months(clause.original_text)
                if months is not None:
                    probation_months = months
                    probation_clause_id = clause.clause_id

    if duration is None or probation_months is None:
        return []

    max_allowed = _max_allowed_probation_months(duration)
    if max_allowed is not None and probation_months <= max_allowed:
        return []  # 没超期，没问题，不产出结果

    if max_allowed is None:
        reason = (
            f"{_duration_label(duration)}，依据《劳动合同法》第十九条不得约定试用期，"
            f"但条款中约定了{probation_months}个月的试用期。"
        )
        suggestion = "删除试用期约定。"
    else:
        reason = (
            f"{_duration_label(duration)}，依据《劳动合同法》第十九条，"
            f"试用期最长不得超过{max_allowed}个月，但条款中约定的试用期为{probation_months}个月，超出法定上限。"
        )
        suggestion = f"将试用期调整为不超过{max_allowed}个月。"

    return [
        ReviewResult(
            clause_id=None,
            related_clause_ids=[cid for cid in (duration_clause_id, probation_clause_id) if cid],
            risk=True,
            risk_level=RiskLevel.HIGH,
            reason=reason,
            legal_basis=[LEGAL_BASIS],
            suggestion=suggestion,
            source=ReviewSource.RULE,
            rule_id=RULE_ID,
        )
    ]
