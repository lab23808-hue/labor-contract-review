"""合同修改闭环相关的 HTTP 路由：批次的创建/查询、任务的发起/确认/拒绝/
放弃、V2 生成、Diff、V2 复审、风险 Diff。

本文件只做 HTTP 层的事情：把请求"翻译"成对应 Service 的一次调用，把
Service / ContractManager 抛出的业务异常映射成 HTTP 状态码。不在这里写
任何状态机判断、任何 V2 生成规则、任何 Diff/风险分类逻辑——修改闭环本身
的规则在 modification/service.py 的 ModificationService 里；V2 生成走
application/v2_generation_service.py 的 V2GenerationService（Part G，
ModificationService 自身不再做这件事）；V2 复审走
application/review_service.py 的 Review Application（与 V1 审查同一个
服务）；Diff 走 application/diff_service.py 的 Diff Application。本文件
保持 API → Application/Service → ContractManager/Workflow/Capability
的分层。

V2 复审、Diff 不调用 ModificationService 上的方法——V2 复审路由自己先用
ContractManager.get_version 把"V2"解析成它背后真正的 contract_id，再调用
Review Application；这正是"Review 不知道 V1/V2，由知道这件事的调用方自己
解析"这条架构约束落在 API 层的体现。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import (
    get_contract_manager,
    get_diff_service,
    get_modification_service,
    get_review_service,
    get_v2_generation_service,
)
from application.diff_service import DiffApplicationService
from application.review_service import ReviewApplicationService
from application.v2_generation_service import V2GenerationService
from contract import ContractError, ContractManager, ContractNotFoundError
from document.parser import DocumentParseError, UnsupportedFormatError
from modification.service import ModificationConflictError, ModificationService, ModificationServiceError
from schemas import ClauseDiffEntry, ContractVersion, ModificationBatch, ModificationTask, ReviewRecord, RiskDiffResult

router = APIRouter(prefix="/contracts", tags=["modification"])


class CreateBatchRequest(BaseModel):
    """POST .../modification-batches 的请求体：律师显式"开始一轮修改"，
    必须指定这一轮修改依据哪一次审查（source_review_id，即某条
    ReviewRecord.review_id）。
    """

    source_review_id: str = Field(..., min_length=1)


class ConfirmModificationRequest(BaseModel):
    """POST .../confirm 的请求体。waiting_confirmation 状态下不需要任何
    字段（manual_text 留空即可）；needs_human 状态下必须提供 manual_text
    （律师手工确定的最终文本）——见 ModificationService.confirm。
    """

    manual_text: str | None = Field(default=None)


class RejectModificationRequest(BaseModel):
    """POST .../reject 的请求体：律师拒绝当前候选时必须给出新的修改意见。"""

    new_instruction: str = Field(..., min_length=1)


class GenerateVersionRequest(BaseModel):
    """POST .../versions 的请求体。batch_id 是必填字段——V2 生成现在以
    批次为单位（Part F/G），不再扫描合同下的全部历史任务。created_by 本阶段
    没有真正的用户体系，默认值和 ContractVersion.created_by 的默认值保持
    一致，允许调用方不传。
    """

    batch_id: str = Field(..., min_length=1)
    created_by: str = Field(default="lawyer", min_length=1)


def _map_service_error(exc: ModificationServiceError) -> HTTPException:
    """ModificationServiceError 是"业务规则不满足"，不是系统故障，统一映射成 409。

    ModificationConflictError 是它的子类，同样按 409 处理——两者都是"当前
    状态不允许这个操作"，不需要在 HTTP 层再区分出两种状态码。
    """
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "/{contract_id}/modification-batches",
    response_model=ModificationBatch,
    status_code=status.HTTP_201_CREATED,
)
def create_batch(
    contract_id: str,
    payload: CreateBatchRequest,
    modification_service: ModificationService = Depends(get_modification_service),
) -> ModificationBatch:
    """律师显式"开始一轮修改"：创建一个新的 ModificationBatch。

    数据流：contract_id + source_review_id → ModificationService.create_batch
    （校验 source_review_id 对应的审查记录确实存在 → 持久化）→ 返回
    batch_id。此后创建的每一条 ModificationTask 都必须显式携带这个
    batch_id（见 POST .../modification-tasks）。
    """
    try:
        return modification_service.create_batch(contract_id, payload.source_review_id)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModificationServiceError as exc:
        raise _map_service_error(exc) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get(
    "/{contract_id}/modification-batches",
    response_model=list[ModificationBatch],
    status_code=status.HTTP_200_OK,
)
def list_batches(
    contract_id: str,
    contract_manager: ContractManager = Depends(get_contract_manager),
) -> list[ModificationBatch]:
    """列出某份合同的全部修改批次。"""
    try:
        return contract_manager.list_batches(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get(
    "/{contract_id}/modification-batches/{batch_id}",
    response_model=ModificationBatch,
    status_code=status.HTTP_200_OK,
)
def get_batch(
    contract_id: str,
    batch_id: str,
    contract_manager: ContractManager = Depends(get_contract_manager),
) -> ModificationBatch:
    """查询单个修改批次当前的状态（前端据此判断"能不能生成 V2"）。"""
    try:
        return contract_manager.get_batch(contract_id, batch_id)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post(
    "/{contract_id}/modification-tasks/{task_id}/start",
    response_model=ModificationTask,
    status_code=status.HTTP_200_OK,
)
def start_modification(
    contract_id: str,
    task_id: str,
    modification_service: ModificationService = Depends(get_modification_service),
) -> ModificationTask:
    """发起（或重新发起）一轮 Modification Agent 调用。

    数据流：contract_id + task_id → ModificationService.start_modification
    （加载任务 → 加载目标条款 → 调用 Agent → Validator 校验 → 记录尝试 →
    持久化）→ 返回更新后的 ModificationTask。
    """
    try:
        return modification_service.start_modification(contract_id, task_id)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModificationServiceError as exc:
        raise _map_service_error(exc) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post(
    "/{contract_id}/modification-tasks/{task_id}/confirm",
    response_model=ModificationTask,
    status_code=status.HTTP_200_OK,
)
def confirm_modification(
    contract_id: str,
    task_id: str,
    payload: ConfirmModificationRequest = ConfirmModificationRequest(),
    modification_service: ModificationService = Depends(get_modification_service),
) -> ModificationTask:
    """律师确认结果（Human-in-the-loop 的确认入口）。

    waiting_confirmation 状态下确认当前候选（manual_text 留空）；
    needs_human 状态下必须提供 manual_text（律师手工确定的最终文本），
    具体校验在 ModificationService.confirm。
    """
    try:
        return modification_service.confirm(contract_id, task_id, manual_text=payload.manual_text)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModificationServiceError as exc:
        raise _map_service_error(exc) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post(
    "/{contract_id}/modification-tasks/{task_id}/reject",
    response_model=ModificationTask,
    status_code=status.HTTP_200_OK,
)
def reject_modification(
    contract_id: str,
    task_id: str,
    payload: RejectModificationRequest,
    modification_service: ModificationService = Depends(get_modification_service),
) -> ModificationTask:
    """律师拒绝当前候选，附带新的修改意见（不满意，重新修改）。"""
    try:
        return modification_service.reject(contract_id, task_id, payload.new_instruction)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModificationServiceError as exc:
        raise _map_service_error(exc) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post(
    "/{contract_id}/modification-tasks/{task_id}/abandon",
    response_model=ModificationTask,
    status_code=status.HTTP_200_OK,
)
def abandon_modification(
    contract_id: str,
    task_id: str,
    modification_service: ModificationService = Depends(get_modification_service),
) -> ModificationTask:
    """律师明确放弃这条修改任务（REJECTED / NEEDS_HUMAN → ABANDONED），
    不再重试，该条款会在 V2 中保留 V1 原文。
    """
    try:
        return modification_service.abandon(contract_id, task_id)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModificationServiceError as exc:
        raise _map_service_error(exc) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post(
    "/{contract_id}/versions",
    response_model=ContractVersion,
    status_code=status.HTTP_201_CREATED,
)
def generate_version(
    contract_id: str,
    payload: GenerateVersionRequest,
    v2_generation_service: V2GenerationService = Depends(get_v2_generation_service),
) -> ContractVersion:
    """生成 V2：以 batch_id 指定的批次为单位（Part G），只有在这个批次里
    全部任务都已落入终态（confirmed/abandoned）且至少存在一条 confirmed
    任务时才允许，具体规则在 V2GenerationService 里。V2_FAILED 的批次可以
    重新调用本接口重试；V2_GENERATED 的批次不能重复生成（一个批次只对应
    一个 V2）。
    """
    try:
        return v2_generation_service.generate(contract_id, batch_id=payload.batch_id, created_by=payload.created_by)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModificationServiceError as exc:
        raise _map_service_error(exc) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/{contract_id}/versions",
    response_model=list[ContractVersion],
    status_code=status.HTTP_200_OK,
)
def list_versions(
    contract_id: str,
    contract_manager: ContractManager = Depends(get_contract_manager),
) -> list[ContractVersion]:
    """列出某份合同的全部非 V1 版本（本阶段实际最多一条：v2）。"""
    try:
        return contract_manager.list_versions(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get(
    "/{contract_id}/versions/{version_number}/diff",
    response_model=list[ClauseDiffEntry],
    status_code=status.HTTP_200_OK,
)
def get_clause_diff(
    contract_id: str,
    version_number: str,
    diff_service: DiffApplicationService = Depends(get_diff_service),
) -> list[ClauseDiffEntry]:
    """条款级 V1/V2 Diff：逐条标记 未修改/已修改，clause_id 对不上时明确标记
    matched=False，不猜测对应关系。
    """
    try:
        return diff_service.clause_diff(contract_id, version_number=version_number)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post(
    "/{contract_id}/versions/{version_number}/review",
    response_model=ReviewRecord,
    status_code=status.HTTP_200_OK,
)
def run_version_review(
    contract_id: str,
    version_number: str,
    contract_manager: ContractManager = Depends(get_contract_manager),
    review_service: ReviewApplicationService = Depends(get_review_service),
) -> ReviewRecord:
    """对 V2 发起一次完全独立的复审（不复用 V1 的 ReviewReport）。

    数据流：先用 ContractManager.get_version 把"V2"（contract_id +
    version_number）解析成它背后真正的 contract_id
    （version.linked_contract_id），再调用 Review Application——这一步
    "解析 V1/V2 关系"只在 API 层做一次，Review Application、Review
    Workflow 全程只看到一个普通 contract_id，不知道、也不需要知道它是
    V1 还是 V2。

    映射方式和 POST /contracts/{id}/review 基本一致，因为内部同样调用
    workflows/review_workflow.py 里未改动的 run_review，会抛出同一组异常；
    多出的 ContractNotFoundError 分支同时覆盖"合同不存在"和"该版本号不
    存在"两种情况（ContractManager.get_version 对这两者抛的是同一个异常）。
    """
    try:
        version = contract_manager.get_version(contract_id, version_number)
        return review_service.review_and_save(version.linked_contract_id, contract_version=version_number)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnsupportedFormatError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"该文件格式的解析尚未实现：{exc}",
        ) from exc
    except DocumentParseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/{contract_id}/versions/{version_number}/risk-diff",
    response_model=RiskDiffResult,
    status_code=status.HTTP_200_OK,
)
def get_risk_diff(
    contract_id: str,
    version_number: str,
    diff_service: DiffApplicationService = Depends(get_diff_service),
) -> RiskDiffResult:
    """V1/V2 风险 Diff：需要 V1、V2 都已经有审查记录，否则 404。"""
    try:
        return diff_service.risk_diff(contract_id, version_number=version_number)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ContractError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
