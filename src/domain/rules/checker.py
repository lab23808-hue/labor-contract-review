"""RuleChecker：主线路（RAG+LLM）之后的规则补充检查。

定位：不是第二条独立审查线路，也不是通用规则引擎——是"针对真实合同测试中
发现的、主线路容易漏检/判断复杂/不稳定的具体问题，逐条沉淀成的补丁"。

RuleChecker 只依赖 Clause 原文本身来判断每条规则用不用得上，不依赖 LLM 的
判断结果或"不确定"标记（LLM 是否说"不确定"以后可以作为优化条件，但不是
RuleChecker 是否工作的依据）。内部维护一个固定的规则函数列表，依次调用；
新增规则就是写一个新文件、在下面的列表里注册一行，不新增顶层模块
（不设计 RuleMatcher / CandidateDetector 这类中间抽象）。
"""

from typing import Callable

from domain.rules import probation_duration, probation_salary
from domain.rules.probation_duration import check_probation_duration
from domain.rules.probation_salary import check_probation_salary
from core import Clause, ReviewResult

# 规则集版本号：由当前实际注册的规则的 RULE_ID 拼接而成，不是手写的独立字符串——
# 这样"注册的规则变了"（新增/删除/改名一条规则）会直接体现在这个值上，不需要
# 另外记着手动同步一个版本号。供 ReviewReport.versions.ruleset_version 记录
# "这份报告是用哪个版本的规则集跑出来的"，评估基准对比前后版本时据此区分。
# 排序是为了让"注册顺序变了但规则集合不变"时版本号不受影响。
RULESET_VERSION = "+".join(sorted([probation_salary.RULE_ID, probation_duration.RULE_ID]))


class RuleChecker:
    """依次跑已注册的规则，返回规则发现的问题（只有真正命中才会有结果）。"""

    def __init__(self) -> None:
        # 已注册的规则：每个函数签名都是 list[Clause] -> list[ReviewResult]，
        # 自己判断适用性、自己提取数据、自己判断、只在发现问题时才返回结果。
        # 新增规则就是写一个新文件、在这里加一行，不新增顶层模块。
        self.rules: list[Callable[[list[Clause]], list[ReviewResult]]] = [
            check_probation_salary,
            check_probation_duration,
        ]
        self.ruleset_version = RULESET_VERSION

    def check(self, clauses: list[Clause]) -> list[ReviewResult]:
        results: list[ReviewResult] = []
        for rule in self.rules:
            results.extend(rule(clauses))
        return results
