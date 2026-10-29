"""risk_resolution 的业务比较逻辑（Part E）。

这是一个纯函数，不调用 LLM、不调用 ClauseReviewer、不碰 ContractManager：
输入"原始风险等级"（任务创建时冻结的 source_review_snapshot.risk_level）
和"修改后风险分析得到的新风险等级"，输出 RiskResolution 这个业务结论。

故意不把这件事交给 ClauseReviewer 或 agents/risk_analyzer.py 自己判断：
Risk Analyzer 的职责只是"对修改后的文本重新跑一次独立审查，得到一个新的
ReviewResult"——它不知道、也不需要知道这次审查是"为了跟谁比较"。"这个新
结果相比原始风险算不算解决"是本系统自己的业务规则，所以单独抽成一个可以
独立测试的纯函数。
"""

from core.review_result import RiskLevel
from core.modification_task import RiskResolution


def determine_risk_resolution(
    original_risk_level: RiskLevel,
    new_risk_level: RiskLevel | None,
) -> RiskResolution:
    """比较"原始风险等级"与"修改后风险分析得到的新风险等级"。

    规则（严重程度用 RiskLevel.severity 比较，none < low < medium < high）：
        - new_risk_level 为 None（Risk Analyzer 调用失败，拿不到新结果）
          → UNKNOWN
        - new_risk_level == NONE（新结果已经没有风险）
          → RESOLVED（不管原始风险等级是什么，风险都已经消失）
        - new_risk_level 严重程度低于 original_risk_level（例如 HIGH → MEDIUM/LOW）
          → PARTIALLY_RESOLVED
        - new_risk_level 严重程度不低于 original_risk_level（持平或更差，
          例如 HIGH → HIGH，或 LOW → MEDIUM）
          → UNRESOLVED
    """
    if new_risk_level is None:
        return RiskResolution.UNKNOWN
    if new_risk_level == RiskLevel.NONE:
        return RiskResolution.RESOLVED
    if new_risk_level.severity < original_risk_level.severity:
        return RiskResolution.PARTIALLY_RESOLVED
    return RiskResolution.UNRESOLVED
