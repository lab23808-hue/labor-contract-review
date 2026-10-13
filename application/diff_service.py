"""DiffApplicationService：Diff 的 Application 层。

架构边界：diff/clause_diff.py、diff/risk_diff.py 都是纯函数（输入 V1/V2 的
Clause 字典 / ReviewResult 列表，输出 Diff 结果），不触碰 ContractManager，
也不知道 ModificationService、API 的存在。本文件是它们和 ContractManager
之间唯一的一层：用 ContractManager 取出 V1/V2 各自的数据，调用这两个纯函数，
组装成对外的返回类型。

这部分逻辑在 Stage 1 时期是 ModificationService.clause_diff /
ModificationService.risk_diff 两个方法；Stage 2 把它们原样搬到这里（算法、
取数逻辑完全不变，只是不再挂在 ModificationService 上）——因为"对比 V1/V2"
本质上是一个独立于"怎么从 V1 改出 V2"的能力，不应该让 Diff 成为
ModificationService 的一部分，否则 Diff 会隐式依赖 Modification 的生命周期
（例如未来如果 Diff 需要支持"V1 对比 V1 的某次重新审查"之类的场景，不应该
被迫先经过 ModificationService）。

本文件不做的事：
    - 不做 HTTP
    - 不重新实现 clause_diff / risk_diff 的匹配/分类算法（原样调用
      diff.clause_diff.clause_diff / diff.risk_diff.risk_diff）
    - 不调用 ModificationService、Review Workflow、LangGraph
"""

from __future__ import annotations

from contract import ContractManager
from diff.clause_diff import clause_diff as _compute_clause_diff
from diff.risk_diff import risk_diff as _compute_risk_diff
from schemas import ClauseDiffEntry, RiskDiffResult


class DiffApplicationService:
    def __init__(self, contract_manager: ContractManager) -> None:
        self.contract_manager = contract_manager

    def clause_diff(self, contract_id: str, version_number: str = "v2") -> list[ClauseDiffEntry]:
        """条款级 V1/V2 Diff：本方法只负责用 ContractManager 取出 V1/V2 的条款，
        真正的逐条匹配/分类算法在 diff.clause_diff.clause_diff（纯函数）。
        """
        version = self.contract_manager.get_version(contract_id, version_number)
        v1_clauses = {
            c.clause_id: c for c in self.contract_manager.get_clauses(contract_id) if c.hierarchy_level == 0
        }
        v2_clauses = {
            c.clause_id: c
            for c in self.contract_manager.get_clauses(version.linked_contract_id)
            if c.hierarchy_level == 0
        }
        return _compute_clause_diff(v1_clauses, v2_clauses)

    def risk_diff(self, contract_id: str, version_number: str = "v2") -> RiskDiffResult:
        """V1/V2 风险 Diff：本方法只负责用 ContractManager 取出 V1/V2 的审查
        结果，真正的匹配/分类算法在 diff.risk_diff.risk_diff（纯函数）。
        """
        version = self.contract_manager.get_version(contract_id, version_number)

        v1_record = self.contract_manager.get_latest_review(contract_id)
        v2_record = self.contract_manager.get_latest_review(version.linked_contract_id)

        entries = _compute_risk_diff(v1_record.report.results, v2_record.report.results)

        return RiskDiffResult(
            contract_id=contract_id,
            v1_review_id=v1_record.review_id,
            v2_review_id=v2_record.review_id,
            entries=entries,
        )
