"""ModificationService：合同修改闭环的编排层。

架构边界（这是本文件存在的唯一理由）：
    API 路由不应该直接持有"什么时候能开始一轮修改""重试到第几轮该转人工"
    这类业务规则——那样规则会散落在 HTTP 层，也没法在没有 FastAPI 的环境里
    单独测试。本文件把这些规则集中放在一处，向上被
    api/routes/{contracts,modification}.py 调用，向下调用 ModificationAgent
    （Agent）、modification.validator.validate（Validator，纯函数）、
    agents.risk_analyzer.analyze_modified_clause（Risk Analyzer，复用
    ClauseReviewer）、modification.risk_resolution.determine_risk_resolution
    （风险对比，纯函数）、ContractManager（持久化）。

本文件的生命周期边界（本次收缩，不再包含的内容见下）：
    律师显式开启一轮修改（创建 ModificationBatch）→ 创建
    ModificationTask（必须携带 batch_id，original_text/source_review_snapshot
    由服务端查出/冻结，不信任客户端）→ Modification Agent → Validator →
    修改后风险分析（Risk Analyzer + risk_resolution）→ 人工确认
    （confirm/reject/abandon）。到 CONFIRMED / ABANDONED 为止，本文件的
    职责结束，不再多做任何事。

本次（在 Stage 2 的基础上）从本文件移除的内容：
    - generate_v2：V2 的生成现在以 ModificationBatch 为单位，且需要先做
      "批次就绪"判断（所有任务都已 CONFIRMED/ABANDONED，且至少一条
      CONFIRMED）——这件事和"怎么从 V1 改出 V2"的编排逻辑现在都在
      app/v2_generation_service.py::V2GenerationService 里，不再
      挂在 ModificationService 上。V2 是否生成成功记录在 ModificationBatch
      上，不会反过来改变 Task 的状态（CONFIRMED 的任务在 V2 生成之后依然是
      CONFIRMED，这是本次需求明确要求的行为）。

本文件不做的事：
    - 不实现任何 LLM 调用细节（那是 ModificationAgent / ClauseReviewer 的职责）
    - 不实现任何持久化细节（那是 ContractManager 的职责）
    - 不重新实现审查 workflow、Clause Diff、Risk Diff、V2 生成（这些不是
      本文件的职责，见上）
    - 不做自动化：确认/拒绝/放弃永远由外部（律师，通过 API）触发，本文件里
      没有任何"自动确认""自动继续下一个任务"的逻辑
"""

from __future__ import annotations

from typing import Optional

from domain.agents.modification_agent import ModificationAgent, ModificationAgentError
from domain.agents.review_agent import ClauseReviewer
from domain.agents.risk_analyzer import analyze_modified_clause
from infra.storage import ContractError, ContractManager, ContractNotFoundError
from domain.modification.risk_resolution import determine_risk_resolution
from domain.modification.validator import validate
from core import (
    Clause,
    ModificationAttempt,
    ModificationBatch,
    ModificationBatchStatus,
    ModificationTask,
    ModificationTaskStatus,
    ReviewResultSnapshot,
    RiskResolution,
)
from core._time import utc_now

# 不阻塞批次就绪（READY_FOR_V2）的终态：批次里每一条任务都必须落到这两个
# 状态之一，且至少有一条是 CONFIRMED，才允许生成 V2。
_BATCH_TERMINAL_STATUSES = (ModificationTaskStatus.CONFIRMED, ModificationTaskStatus.ABANDONED)


class ModificationServiceError(Exception):
    """业务规则不满足（状态不对、前置条件缺失等），不是系统故障。"""


class ModificationConflictError(ModificationServiceError):
    """检测到多个修改任务指向同一个/关联的条款，需要律师先合并再继续。"""


def compute_batch_readiness(tasks: list[ModificationTask]) -> tuple[bool, list[ModificationTask], list[ModificationTask]]:
    """批次就绪判断（Part F）：纯函数，只依据传入的任务列表。

    返回 (是否就绪, 阻塞中的任务, 已确认的任务)。就绪条件：
        - 没有任何任务停留在 PENDING / WAITING_CONFIRMATION / REJECTED /
          NEEDS_HUMAN（阻塞列表为空）；
        - 且至少有一条任务是 CONFIRMED（否则生成 V2 没有意义）。
    """
    blocking = [t for t in tasks if t.status not in _BATCH_TERMINAL_STATUSES]
    confirmed = [t for t in tasks if t.status == ModificationTaskStatus.CONFIRMED]
    ready = not blocking and len(confirmed) > 0
    return ready, blocking, confirmed


class ModificationService:
    def __init__(
        self,
        contract_manager: ContractManager,
        agent: ModificationAgent,
        reviewer: Optional[ClauseReviewer] = None,
    ) -> None:
        self.contract_manager = contract_manager
        self.agent = agent
        # Risk Analyzer（Part D）需要复用 ClauseReviewer 的 RAG→LLM 链路；
        # 设为可选只是为了兼容旧测试脚本里不构造真实 LLM 的场景——真实
        # start_modification 在 reviewer 为 None 时会把这一步的失败按
        # "Risk Analyzer 调用失败"同样处理（risk_analysis_error 记录原因），
        # 不会让整个 start_modification 失败。
        self.reviewer = reviewer

    # ------------------------------------------------------------------
    # 批次（ModificationBatch）
    # ------------------------------------------------------------------

    def create_batch(self, contract_id: str, source_review_id: str) -> ModificationBatch:
        """律师显式"开始一轮修改"：校验 source_review_id 对应的审查记录确实
        存在，再创建一个新的 ModificationBatch。
        """
        try:
            self.contract_manager.get_review(contract_id, source_review_id)
        except ContractNotFoundError as exc:
            raise ModificationServiceError(
                f"合同 {contract_id} 不存在审查记录 {source_review_id}，无法以此为依据开始一轮修改"
            ) from exc
        return self.contract_manager.create_batch(contract_id, source_review_id)

    def _sync_batch_status(self, contract_id: str, batch_id: str) -> ModificationBatch:
        """在任务状态发生终态变化（confirm/reject/abandon）之后，重新计算
        批次是否就绪，并据此把 IN_PROGRESS 推进为 READY_FOR_V2（或反过来，
        理论上不会发生——任务一旦全部落入终态就不会再回退到阻塞状态）。

        只在批次仍处于 IN_PROGRESS / READY_FOR_V2 时才会被这个方法改动；
        V2_GENERATING / V2_GENERATED / V2_FAILED 由
        app/v2_generation_service.py 独立管理，本方法不会触碰。
        """
        batch = self.contract_manager.get_batch(contract_id, batch_id)
        if batch.status not in (ModificationBatchStatus.IN_PROGRESS, ModificationBatchStatus.READY_FOR_V2):
            return batch

        tasks = [self.contract_manager.get_modification_task(contract_id, tid) for tid in batch.task_ids]
        ready, _blocking, _confirmed = compute_batch_readiness(tasks)
        new_status = ModificationBatchStatus.READY_FOR_V2 if ready else ModificationBatchStatus.IN_PROGRESS
        if new_status != batch.status:
            batch.status = new_status
            batch.updated_at = utc_now()
            batch = self.contract_manager.update_batch(batch)
        return batch

    # ------------------------------------------------------------------
    # 任务冲突检查 / 创建
    # ------------------------------------------------------------------

    def check_task_conflict(self, contract_id: str, target_clause_id: str) -> None:
        """创建新任务前调用：同一个条款已经存在一条尚未进入终态的任务时拒绝创建。

        只做"同一个 target_clause_id"这种最简单、最不会误判的判断——不尝试
        通过 related_clause_ids 或语义相似度去猜"这两个任务算不算关联"，
        那属于本阶段明确排除的"复杂任务依赖图"。CONFIRMED / ABANDONED 都是
        终态，不算冲突（可以针对同一条款再开一轮新的修改）。
        """
        existing = self.contract_manager.list_modification_tasks(contract_id)
        for task in existing:
            if task.target_clause_id == target_clause_id and not task.is_terminal:
                raise ModificationConflictError(
                    f"条款 {target_clause_id} 已存在一条未完成的修改任务（{task.task_id}，"
                    f"状态：{task.status.value}），请先处理完该任务或与其合并，"
                    "不要为同一个条款重复创建修改任务。"
                )

    def create_task(
        self,
        contract_id: str,
        batch_id: str,
        target_clause_id: str,
        lawyer_instruction: str,
    ) -> ModificationTask:
        """创建一条修改任务：校验批次存在且仍可接收新任务，服务端查出条款原文
        和当时的审查结果快照，再落盘。

        original_text 绝不接受客户端传入的值——必须用 contract_id +
        target_clause_id 从 ContractManager.get_clauses 里查出真实原文，
        防止律师（或前端 bug）提交一份被篡改过的"原文"，污染审计记录。
        """
        batch = self.contract_manager.get_batch(contract_id, batch_id)
        if batch.source_contract_id != contract_id:
            raise ModificationServiceError(f"批次 {batch_id} 不属于合同 {contract_id}")
        if batch.status != ModificationBatchStatus.IN_PROGRESS:
            raise ModificationServiceError(
                f"批次 {batch_id} 当前状态为 {batch.status.value}，不再接受新的修改任务"
                "（只有 in_progress 状态的批次可以创建任务）。"
            )

        clauses = self.contract_manager.get_clauses(contract_id)
        clause = self._find_clause(clauses, target_clause_id)
        if clause is None:
            raise ModificationServiceError(f"合同 {contract_id} 中找不到条款 {target_clause_id}")

        review_record = self.contract_manager.get_review(contract_id, batch.source_review_id)
        review_result = self._find_review_result_in_report(review_record.report, target_clause_id)
        if review_result is None:
            raise ModificationServiceError(
                f"审查记录 {batch.source_review_id} 中找不到条款 {target_clause_id} 关联的审查结果，"
                "无法以此为依据创建修改任务。"
            )
        snapshot = ReviewResultSnapshot.from_review_result(review_result)

        self.check_task_conflict(contract_id, target_clause_id)

        task = self.contract_manager.create_modification_task(
            contract_id=contract_id,
            clause_id=target_clause_id,
            original_text=clause.original_text,
            lawyer_instruction=lawyer_instruction,
            batch_id=batch_id,
            source_review_id=batch.source_review_id,
            source_review_snapshot=snapshot,
        )

        batch.task_ids = [*batch.task_ids, task.task_id]
        batch.updated_at = utc_now()
        self.contract_manager.update_batch(batch)
        return task

    # ------------------------------------------------------------------
    # 单个任务的修改 / 确认 / 拒绝 / 放弃
    # ------------------------------------------------------------------

    def start_modification(self, contract_id: str, task_id: str) -> ModificationTask:
        """发起（或重新发起）一轮 Modification Agent 调用。

        永远基于 task.original_text（V1 原文）+ task.lawyer_instructions
        （全部历史意见）重新生成，不基于上一轮候选——这是"不允许在错误候选
        基础上继续改"这条硬约束的落地方式：Agent 根本不会看到上一轮候选
        文本，因为 build_modification_messages 从来不读 current_modified_text。

        Validator 通过后，紧接着跑一次修改后风险分析（Risk Analyzer，复用
        ClauseReviewer）：失败不会阻塞流程，只会把失败原因记进
        risk_analysis_error、risk_resolution 置为 UNKNOWN，任务依然进入
        WAITING_CONFIRMATION——这是 Part D 明确要求的行为（"从不阻塞或
        静默吞掉"）。
        """
        task = self.contract_manager.get_modification_task(contract_id, task_id)
        if not task.can_start:
            raise ModificationServiceError(
                f"任务 {task_id} 当前状态为 {task.status.value}，不允许发起新的修改（"
                f"只有 pending / rejected 状态可以调用 start）。"
            )
        if task.attempts_exhausted:
            raise ModificationServiceError(f"任务 {task_id} 已用满 {len(task.modification_attempts)} 轮重试，请转人工处理。")

        clauses = self.contract_manager.get_clauses(contract_id)
        clause = self._find_clause(clauses, task.target_clause_id)
        if clause is None:
            raise ModificationServiceError(f"合同 {contract_id} 中找不到条款 {task.target_clause_id}")

        sibling_article_numbers = self._sibling_article_numbers(clauses, task.target_clause_id)

        attempt_number = len(task.modification_attempts) + 1
        latest_instruction = task.lawyer_instructions[-1]

        try:
            candidate = self.agent.generate_candidate(
                clause=clause,
                review_result=task.source_review_snapshot,
                lawyer_instructions=task.lawyer_instructions,
            )
        except ModificationAgentError as exc:
            attempt = ModificationAttempt(
                attempt_number=attempt_number,
                lawyer_instruction=latest_instruction,
                candidate_text=None,
                reason="",
                legal_basis=[],
                validator_passed=False,
                validator_errors=[str(exc)],
            )
            return self._record_attempt(task, attempt, passed=False)

        result = validate(clause, candidate, sibling_article_numbers=sibling_article_numbers)

        risk_analysis = None
        risk_analysis_error = None
        risk_resolution: Optional[RiskResolution] = None
        if result.passed:
            risk_analysis, risk_analysis_error, risk_resolution = self._run_risk_analysis(
                clause=clause,
                candidate_text=candidate.modified_text,
                original_risk_level=task.source_review_snapshot.risk_level,
            )

        attempt = ModificationAttempt(
            attempt_number=attempt_number,
            lawyer_instruction=latest_instruction,
            candidate_text=candidate.modified_text,
            reason=candidate.reason,
            legal_basis=candidate.legal_basis,
            validator_passed=result.passed,
            validator_errors=result.errors,
            risk_analysis=risk_analysis,
            risk_analysis_error=risk_analysis_error,
            risk_resolution=risk_resolution,
        )
        return self._record_attempt(task, attempt, passed=result.passed, candidate_text=candidate.modified_text)

    def _run_risk_analysis(self, clause: Clause, candidate_text: str, original_risk_level):
        """跑一次修改后风险分析，捕获任何异常（Part D 的硬约束：Risk Analyzer
        本身不做兜底，兜底逻辑必须放在这里，调用方——也就是本方法——负责
        捕获、记录错误、把 risk_resolution 置为 UNKNOWN，绝不向上传播、
        绝不阻塞 start_modification 的主流程）。
        """
        if self.reviewer is None:
            return None, "未配置 Risk Analyzer（缺少 ClauseReviewer 依赖）", RiskResolution.UNKNOWN
        try:
            risk_result = analyze_modified_clause(self.reviewer, clause, candidate_text)
        except Exception as exc:  # noqa: BLE001 - Part D 明确要求捕获任意异常，不做静默吞掉而是记录
            return None, str(exc), RiskResolution.UNKNOWN
        resolution = determine_risk_resolution(original_risk_level, risk_result.risk_level)
        return risk_result, None, resolution

    def _record_attempt(
        self,
        task: ModificationTask,
        attempt: ModificationAttempt,
        passed: bool,
        candidate_text: Optional[str] = None,
    ) -> ModificationTask:
        task.modification_attempts.append(attempt)
        task.updated_at = utc_now()
        if passed:
            task.status = ModificationTaskStatus.WAITING_CONFIRMATION
            task.current_modified_text = candidate_text
        elif task.attempts_exhausted:
            task.status = ModificationTaskStatus.NEEDS_HUMAN
            task.current_modified_text = None
        else:
            # 校验没通过，但还有重试机会：留在 pending，等待律师看到 Validator
            # 报错后决定是否补充意见再次 start（不自动重试）。
            task.status = ModificationTaskStatus.PENDING
            task.current_modified_text = None
        return self.contract_manager.update_modification_task(task)

    def confirm(self, contract_id: str, task_id: str, manual_text: Optional[str] = None) -> ModificationTask:
        """律师确认结果。Agent 自己不能调用这个方法把自己的产出标记为已确认。

        两种可被确认的状态：
            - waiting_confirmation：确认当前这一轮候选（current_modified_text）；
            - needs_human：已经转人工的任务，律师线下/手工确定了最终文本后，
              通过 manual_text 传入这份文本一并确认（Part B 要求的
              "NEEDS_HUMAN → 手工确认结果 → CONFIRMED" 这条转换）。
        """
        task = self.contract_manager.get_modification_task(contract_id, task_id)
        if task.status == ModificationTaskStatus.WAITING_CONFIRMATION:
            pass
        elif task.status == ModificationTaskStatus.NEEDS_HUMAN:
            if not manual_text or not manual_text.strip():
                raise ModificationServiceError(
                    f"任务 {task_id} 处于 needs_human 状态，确认时必须提供 manual_text（律师手工确定的最终文本）。"
                )
            task.current_modified_text = manual_text.strip()
        else:
            raise ModificationServiceError(
                f"任务 {task_id} 当前状态为 {task.status.value}，不能确认"
                "（只有 waiting_confirmation / needs_human 状态可以确认）。"
            )
        task.status = ModificationTaskStatus.CONFIRMED
        task.confirmed_at = utc_now()
        task.updated_at = task.confirmed_at
        updated = self.contract_manager.update_modification_task(task)
        self._sync_batch_status(contract_id, task.batch_id)
        return updated

    def reject(self, contract_id: str, task_id: str, new_instruction: str) -> ModificationTask:
        """律师拒绝当前候选，附带一条新的修改意见（追加，不覆盖历史）。"""
        if not new_instruction or not new_instruction.strip():
            raise ModificationServiceError("拒绝修改时必须提供新的修改意见")
        task = self.contract_manager.get_modification_task(contract_id, task_id)
        if task.status != ModificationTaskStatus.WAITING_CONFIRMATION:
            raise ModificationServiceError(
                f"任务 {task_id} 当前状态为 {task.status.value}，不能拒绝（只有 waiting_confirmation 状态可以拒绝）。"
            )

        task.lawyer_instructions = [*task.lawyer_instructions, new_instruction.strip()]
        task.current_modified_text = None
        task.updated_at = utc_now()
        task.status = ModificationTaskStatus.NEEDS_HUMAN if task.attempts_exhausted else ModificationTaskStatus.REJECTED
        updated = self.contract_manager.update_modification_task(task)
        self._sync_batch_status(contract_id, task.batch_id)
        return updated

    def abandon(self, contract_id: str, task_id: str) -> ModificationTask:
        """律师明确放弃这条修改任务（不再重试）：REJECTED / NEEDS_HUMAN → ABANDONED。

        这是本次新增的 API 面：之前只有"重试"和"转人工"两个结局，没有"主动
        放弃"这条路径——有些任务在人工介入后，律师可能直接决定"这一条不改
        了，保留 V1 原文"，不需要先造一个能通过 Validator 的候选再去拒绝它。
        """
        task = self.contract_manager.get_modification_task(contract_id, task_id)
        if task.status not in (ModificationTaskStatus.REJECTED, ModificationTaskStatus.NEEDS_HUMAN):
            raise ModificationServiceError(
                f"任务 {task_id} 当前状态为 {task.status.value}，不能放弃"
                "（只有 rejected / needs_human 状态可以放弃）。"
            )
        task.status = ModificationTaskStatus.ABANDONED
        task.current_modified_text = None
        task.updated_at = utc_now()
        updated = self.contract_manager.update_modification_task(task)
        self._sync_batch_status(contract_id, task.batch_id)
        return updated

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _find_clause(clauses: list[Clause], clause_id: str) -> Optional[Clause]:
        for clause in clauses:
            if clause.clause_id == clause_id:
                return clause
        return None

    @staticmethod
    def _find_review_result_in_report(report, clause_id: str):
        for result in report.results:
            if result.clause_id == clause_id or clause_id in result.related_clause_ids:
                return result
        return None

    @staticmethod
    def _sibling_article_numbers(clauses: list[Clause], target_clause_id: str) -> list[str]:
        numbers: list[str] = []
        for clause in clauses:
            if clause.clause_id == target_clause_id:
                continue
            article_no = clause.metadata.get("article_no") if isinstance(clause.metadata, dict) else None
            if article_no:
                numbers.append(article_no)
        return numbers
