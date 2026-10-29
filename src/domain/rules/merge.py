"""merge_review_results：把主线路（LLM）结果和规则补充结果合并成最终列表。

语义必须明确：ReviewResult 是"风险点"的结果，不是"条款"的结果——一个 Clause
可以对应多条 ReviewResult（schemas.ReviewReport.results 本来就是不做去重
约束的扁平列表）。这里的合并是纯拼接，LLM 结果和规则结果都完整保留：
    - 不做覆盖：规则命中不会删除或顶替 LLM 已经产出的结果；
    - 不做去重：不判断两条结果是不是"同一个问题"；
    - 不比较置信度：规则只在真正发现问题时才产出结果（规则自身的设计约定），
      规则结果的存在本身就是确定性复核后的补充证据，不需要跟 LLM 结果打分对比。

调用方（未来的 review/pipeline.py）需要知道：合并后列表的长度不等于条款
数量。25 个 Clause 全部走完主线路会产出 25 条 LLM 结果；如果其中 2 条又被
规则命中，合并后是 27 条，不是 25 条——多出来的 2 条是同一条款的规则补充
结果，不是 2 个新条款，ReviewReport 在展示/统计时要按这个语义处理，不能把
条目数直接当成条款数。

v1 不做同类风险的语义去重/合并——如果后续真实合同测试发现规则和 LLM
重复率高到影响可读性，再单独设计，这次不提前做。
"""

from core import ReviewResult


def merge_review_results(
    llm_results: list[ReviewResult], rule_results: list[ReviewResult]
) -> list[ReviewResult]:
    """拼接 LLM 结果和规则结果，两者都完整保留，不覆盖、不去重。"""
    return llm_results + rule_results
