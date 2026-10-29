"""风险 Diff：纯函数，输入 V1/V2 的 ReviewResult 列表，输出分类后的风险 Diff 条目。

不调用 ContractManager、不 import modification.service——V1/V2 的
ReviewResult 列表由调用方（modification/service.py）先用 ContractManager
取好（从各自的 ReviewRecord.report.results 里取出），再传进来；
contract_id / review_id 这类“这是哪份合同、哪次审查”的信息也由调用方
自己组装进最终的 RiskDiffResult，本模块只产出 entries 列表。
"""

from typing import Optional

from core import ReviewResult, ReviewSource, RiskDiffEntry

# --- 本次修复记录（P0 bug，
#
# 旧实现的 _result_key() 对规则来源的结果只用 rule_id 作为匹配键：
#     return ("rule", result.rule_id)
# risk_diff() 内部又是用字典推导式构建 v1_by_key / v2_by_key——同一条规则
# 命中多个不同条款时（例如 probation_salary 规则可能在一份合同里对多处
# “试用期工资”条款分别命中，产出多条 rule_id 相同但 clause_id 不同的
# ReviewResult），这些结果会共享同一个 key，字典推导式会用后面的结果静默
# 覆盖前面的，导致 V1/V2 Diff 报告里同一规则命中的多个条款只剩一条——
# 这不是“结果偶然一样所以合并”，而是结果本身对应不同条款却被当成了同一条。
#
# 为什么不能简单改成“全部按 related_clause_ids 匹配”（需求原文的提法）：
#     - LLM 来源的结果永远有 clause_id（schema 用 model_validator 强制
#       保证），条款级问题按 clause_id 匹配最直接、不产生歧义，这部分逻辑
#       本次不改动。
#     - 规则来源的结果里，clause_id 和 related_clause_ids 是两种不同性质
#       的字段：单条款问题（如 probation_salary）用 clause_id；跨条款问题
#       （如 probation_duration，合同期限条款 + 试用期条款）用
#       related_clause_ids，clause_id 为 None；真正“合同级、没有对应条款”
#       的问题（schema 文档提到的“合同缺少必备条款”这类，当前两条已实现的
#       规则都不属于这种）则两者都为空。
#       一律改成按 related_clause_ids 匹配会让“单条款问题”的匹配退化成
#       “空列表”，反而比现在更容易互相覆盖；必须按“这条结果实际有什么可用
#       的条款信息”分情况处理，不能用同一个字段一刀切。
#
# 新 key 的设计：rule_id 相同不再代表同一条风险——必须把"命中了哪些条款"
# 也编进 key。按优先级取可用的条款信息：
#     1. clause_id（单条款问题）
#     2. related_clause_ids 排序后的元组（跨条款问题）
#     3. 都没有时，退化为只用 rule_id（真正的合同级问题，目前两条规则都不
#        会走到这一分支；如果未来某条规则会对同一张合同产出多条“完全没有
#        条款信息”的同 rule_id 结果，现有字段不足以区分它们——这种情况
#        现有数据模型本身就无法可靠匹配，不在本次范围内通过扩大数据模型
#        解决，留给后续如果真的出现这种规则时再设计）。
#
# 这样设计后：
#     - 同一规则命中不同条款 → key 不同 → 不会互相覆盖（修复 bug #1）。
#     - 同一规则命中同一条款，V1/V2 都有 → key 相同 → 正确匹配为一条。
#     - 同一规则在 V1/V2 命中的条款发生变化（不是同一个 clause_id/
#       related_clause_ids）→ V1 侧的 key 只在 v1_by_key 里，V2 侧的 key
#       只在 v2_by_key 里 → 分别产出 "unmatched"（V1 这条没了）和 "new"
#       （V2 这条是新出现的）两条 entry，而不是被错误地当成"同一条匹配上
#       了、没有变化"（这是比"条目变少"更隐蔽的一种数据丢失——内容被错误
#       合并，而不是消失）。
# ---------------------------------------------------------------------------


def _result_key(result: ReviewResult) -> tuple:
    """用于 V1/V2 结果匹配的稳定标识。

    设计决策：
        - LLM 来源的结果永远带 clause_id（schema 已经用 model_validator
          强制保证），条款级问题按 clause_id 匹配是最直接、最不会产生
          歧义的方式——clause_id 在 V1/V2 之间因为切分方式不变而保持对齐。
        - 规则来源的结果永远带 rule_id（同样是 schema 强制保证），但
          rule_id 相同不代表同一条风险——同一条规则可能命中多个不同条款。
          必须结合这条结果实际携带的条款信息（clause_id，或 clause_id
          为空时的 related_clause_ids）一起作为 key，否则不同条款的结果
          会互相覆盖（见上方本次修复记录）。
    """
    if result.source == ReviewSource.LLM:
        return ("clause", result.clause_id)
    if result.clause_id is not None:
        return ("rule", result.rule_id, "clause", result.clause_id)
    if result.related_clause_ids:
        return ("rule", result.rule_id, "related", tuple(sorted(result.related_clause_ids)))
    # 真正没有任何条款信息的合同级问题：现有两条规则都不会走到这里；
    # 如果未来出现这种规则且同一 rule_id 产出多条结果，现有字段不足以
    # 区分它们，属于已知限制（见上方记录），不在本次范围内解决。
    return ("rule", result.rule_id)


def _clause_ref(result: ReviewResult) -> Optional[str]:
    """这条结果关联哪些条款，用于展示（v1_clause_ref / v2_clause_ref）。

    直接从实际的 ReviewResult 取值，不再从 key 里反推——key 的职责只是
    "判断是不是同一条"，不是"展示用的文本"，两者分开后 key 的设计可以
    自由调整，不受展示格式约束。
    """
    if result.clause_id is not None:
        return result.clause_id
    if result.related_clause_ids:
        return ",".join(sorted(result.related_clause_ids))
    return None


def _describe_key(result: ReviewResult) -> str:
    """用于 description 文案里标注"这是哪条结果"，取代旧实现里直接拼 key 的 ref_value。"""
    if result.source == ReviewSource.LLM:
        return f"clause_id={result.clause_id}"
    ref = _clause_ref(result)
    if ref is not None:
        return f"rule_id={result.rule_id}（关联条款：{ref}）"
    return f"rule_id={result.rule_id}（无对应条款）"


def _categorize(v1_result: Optional[ReviewResult], v2_result: Optional[ReviewResult]) -> RiskDiffEntry:
    if v1_result is not None and v2_result is None:
        # 只有 V1 有这条结果：既可能是"这条规则/条款在 V2 里已经不适用了"，
        # 也可能是切分结构发生了意外变化——不猜测，明确标记为无法可靠匹配。
        return RiskDiffEntry(
            category="unmatched",
            description=f"V1 中存在对应结果（{_describe_key(v1_result)}），但在 V2 复审结果中找不到可靠匹配，无法判断该风险是否已解决。",
            v1_risk_level=v1_result.risk_level,
            v2_risk_level=None,
            v1_clause_ref=_clause_ref(v1_result),
            v2_clause_ref=None,
        )
    if v1_result is None and v2_result is not None:
        return RiskDiffEntry(
            category="new",
            description=f"V2 复审中新出现的结果（{_describe_key(v2_result)}），V1 中不存在对应项。",
            v1_risk_level=None,
            v2_risk_level=v2_result.risk_level,
            v1_clause_ref=None,
            v2_clause_ref=_clause_ref(v2_result),
        )

    assert v1_result is not None and v2_result is not None
    if v1_result.risk_level == v2_result.risk_level:
        category = "unchanged"
    elif v1_result.risk and not v2_result.risk:
        category = "resolved"
    else:
        category = "changed"

    return RiskDiffEntry(
        category=category,
        description=v2_result.reason or v1_result.reason,
        v1_risk_level=v1_result.risk_level,
        v2_risk_level=v2_result.risk_level,
        v1_clause_ref=_clause_ref(v1_result),
        v2_clause_ref=_clause_ref(v2_result),
    )


def risk_diff(v1_results: list[ReviewResult], v2_results: list[ReviewResult]) -> list[RiskDiffEntry]:
    """对比 V1/V2 的全部审查结果（按 _result_key 匹配），返回分类后的 Diff 条目列表。"""
    v1_by_key = {_result_key(r): r for r in v1_results}
    v2_by_key = {_result_key(r): r for r in v2_results}

    entries: list[RiskDiffEntry] = []
    for key in sorted(set(v1_by_key) | set(v2_by_key), key=str):
        v1_result = v1_by_key.get(key)
        v2_result = v2_by_key.get(key)
        entries.append(_categorize(v1_result, v2_result))
    return entries
