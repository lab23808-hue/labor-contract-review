"""probation_salary_rule：试用期工资比例是否低于正式工资标准的百分之八十。

这是一条针对性的规则补丁，不是通用规则引擎的一部分——只处理“试用期工资为
正式工资（标准）的百分之X / X%”这种直接给出比例的表述，用确定性计算复核
百分比数字，减少 LLM 偶发看错/算错数字的风险。

不处理：用绝对金额表达、需要换算比例的情况（比如“试用期3000元，转正后5000
元”）——这种情况以后如果真实测试中发现有需要再加，不是这一版要覆盖的。

只在发现问题（低于80%）时才产出结果；没发现问题就返回空列表，不产出“合规
确认”类的结果。
"""

import re
from typing import Optional

from schemas import Clause, ReviewResult, ReviewSource, RiskLevel

RULE_ID = "probation_salary_below_80_percent"
LEGAL_BASIS = "《劳动合同法》第二十条"
MINIMUM_PERCENT = 80

_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

# “试用期工资”和百分比之间允许隔最多 20 个字符（比如“试用期工资为正式工资标准的百分之五十”）。
#
# 字符类必须包含“零”——“百分之零”（0%）是比任何法定下限都低的典型违规表达，
# 遗漏“零”会让 _extract_percent 直接返回 None，规则把它当成“没写比例”跳过，
# 造成漏检（见 docs/PITFALLS.md P-27）。百分号同时接受半角 % 和全角 ％，
# 两种写法在实际合同文本里都会出现。
_PERCENT_RE = re.compile(
    r"试用期工资[^。\n]{0,20}?(?:百分之(?P<cn>[零一二三四五六七八九十百]{1,3})|(?P<num>\d{1,3})\s*[%％])"
)


def _cn_percent_to_int(text: str) -> Optional[int]:
    """把“五十”“八十五”“百”这类中文百分比数字转成 int。只覆盖 0~100 常见表达。"""
    if text in ("百", "一百"):
        return 100
    if text in _CN_DIGIT:
        return _CN_DIGIT[text]
    match = re.fullmatch(r"([一二三四五六七八九])?十([一二三四五六七八九])?", text)
    if match:
        tens = _CN_DIGIT[match.group(1)] if match.group(1) else 1
        units = _CN_DIGIT[match.group(2)] if match.group(2) else 0
        return tens * 10 + units
    return None


def _extract_percent(clause_text: str) -> Optional[int]:
    match = _PERCENT_RE.search(clause_text)
    if not match:
        return None
    if match.group("num") is not None:
        return int(match.group("num"))
    return _cn_percent_to_int(match.group("cn"))


def check_probation_salary(clauses: list[Clause]) -> list[ReviewResult]:
    """扫描条款，找出试用期工资比例低于 80% 的条款。"""
    results: list[ReviewResult] = []
    for clause in clauses:
        percent = _extract_percent(clause.original_text)
        if percent is None or percent >= MINIMUM_PERCENT:
            continue
        results.append(
            ReviewResult(
                clause_id=clause.clause_id,
                risk=True,
                risk_level=RiskLevel.HIGH,
                reason=(
                    f"条款约定试用期工资为正式工资标准的百分之{percent}，"
                    f"低于《劳动合同法》第二十条规定的百分之{MINIMUM_PERCENT}下限。"
                ),
                legal_basis=[LEGAL_BASIS],
                suggestion=f"将试用期工资调整为不低于正式工资标准的百分之{MINIMUM_PERCENT}。",
                source=ReviewSource.RULE,
                rule_id=RULE_ID,
            )
        )
    return results
