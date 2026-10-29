"""ReviewApplicationService：Review 的 Application 层（API 和 Review Workflow
之间的唯一一层）。

架构边界（这是本文件存在的唯一理由）：
    Review Workflow（workflow/review_workflow.py）是一次完整合同审查的
    流程编排本身，它已经是"审查能力"这件事的正确归宿——不需要在它上面再包
    一层"ReviewCapability"之类的壳。但"审查完了要不要存、存成哪个版本号"
    这个决定不应该是 Workflow 自己做的（Workflow 甚至不知道"版本号"这个
    概念），也不应该散落在 API 路由里手写（之前 api/routes/contracts.py
    自己构造 ReviewReport、自己调用 save_review）。本文件就是这一层：
    调用 Review Workflow → 拿到 ReviewReport → 按 save_result 决定是否持久化
    → 把结果交回调用方。

本文件不做的事：
    - 不做 HTTP（不知道 FastAPI、HTTPException 的存在）
    - 不碰 LangGraph 节点内部（不知道 ReviewGraphState 的存在）
    - 不做任何 LLM Prompt / RAG 相关逻辑（那是 reviewer 自己的事）
    - 不做 Diff（那是 app/diff_service.py 的职责）
    - 不区分 V1/V2：本文件收到的 contract_id 可能是某份合同自己的
      contract_id，也可能是 ContractVersion.linked_contract_id（V2 的真正
      数据宿主）——两者在本文件看来完全对等，都只是"一个 contract_id"。
      是 V1 还是 V2 由调用方（API 路由）自己通过 ContractVersion 解析出来，
      本文件不做任何相关判断，这正是"Review 不知道 V1/V2"这条架构约束
      在 Application 层的延续。

contract_version 参数的定位：它只是 ContractManager.save_review 本来就有的
一个"展示用标签"（只影响 review_id 的编号字符串是 "v1_00N" 还是
"v2_00N"，不影响实际存到了哪个 contract_id 的目录下——真正区分 V1/V2 数据的
是 contract_id 本身）。这个标签天然就需要由"知道这次审查是对谁发起的"调用方
显式提供（ContractManager.save_review 一直是这样设计的，见 infra/storage/manager.py
里 P-22 的说明），本文件原样转发，不代表本文件"知道" V1/V2 的业务含义。
"""

from __future__ import annotations

from domain.agents.review_agent import ClauseReviewer
from infra.storage import ContractManager
from domain.rules import RuleChecker
from core import ReviewRecord, ReviewReport
from workflow.review_workflow import run_review


class ReviewApplicationService:
    def __init__(
        self,
        contract_manager: ContractManager,
        reviewer: ClauseReviewer,
        rule_checker: RuleChecker,
    ) -> None:
        self.contract_manager = contract_manager
        self.reviewer = reviewer
        self.rule_checker = rule_checker

    def _run(self, contract_id: str) -> ReviewReport:
        """只跑一次 Review Workflow，不做任何持久化判断。"""
        return run_review(contract_id, self.contract_manager, self.reviewer, self.rule_checker)

    def review(
        self,
        contract_id: str,
        save_result: bool = True,
        contract_version: str = "v1",
    ) -> ReviewReport:
        """发起一次审查；save_result=True 时额外持久化一份 ReviewRecord。

        返回值始终是 ReviewReport（不是 ReviewRecord），和 Stage 1 时期
        POST /contracts/{id}/review 的响应体契约保持一致——是否保存只影响
        "有没有多做一步落盘"，不改变这次调用本身返回什么。
        """
        report = self._run(contract_id)
        if save_result:
            self.contract_manager.save_review(contract_id, report, contract_version=contract_version)
        return report

    def review_and_save(self, contract_id: str, contract_version: str = "v1") -> ReviewRecord:
        """发起一次审查并持久化，返回保存后的 ReviewRecord（带 review_id）。

        V2 复审（之前是 ModificationService.run_v2_review）需要的正是这个
        形状的返回值：调用方（API 路由）先用 ContractVersion 把"V2"这个
        说法解析成它背后真正的 contract_id，再调用本方法，传入对应的
        version_number 作为展示标签。
        """
        report = self._run(contract_id)
        return self.contract_manager.save_review(contract_id, report, contract_version=contract_version)

    def review_version(self, contract_id: str, version_number: str) -> ReviewRecord:
        """解析版本号对应的 linked_contract_id，再发起独立复审。"""
        version = self.contract_manager.get_version(contract_id, version_number)
        return self.review_and_save(version.linked_contract_id, contract_version=version_number)
