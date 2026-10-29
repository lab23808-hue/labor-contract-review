"""POST /contracts：上传合同文件，创建一份新的合同记录。

本文件只做 HTTP 层的事情：
    解析 multipart 请求 → 把上传内容落到一个安全的临时文件 →
    调用 ContractManager.create_contract 完成真正的创建 → 序列化返回。

合同创建的全部业务逻辑（生成 contract_id、保存原始文件、计算 sha256、
写 metadata、失败时清理目录）完全在 ContractManager 里，本文件不重复实现、
也不绕过它——本文件唯一的职责是把 HTTP 请求"翻译"成 ContractManager 认识的
一次函数调用。
"""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from api.dependencies import get_contract_service, get_modification_service, get_review_service
from api.errors import (
    ContractError,
    ContractNotFoundError,
    DocumentParseError,
    ModificationConflictError,
    ModificationServiceError,
    UnsupportedFormatError,
)
from app.contract_service import ContractApplicationService
from app.review_service import ReviewApplicationService
from core import Clause, Contract, ModificationTask, ReviewRecord, ReviewReport

router = APIRouter(prefix="/contracts", tags=["contracts"])


class ModificationTaskCreate(BaseModel):
    """POST /contracts/{contract_id}/modification-tasks 的请求体。

    这是 HTTP 层的输入 DTO，不是 schemas 里的业务对象：真正的
    ModificationTask（含 task_id、status、created_at、original_text、
    source_review_snapshot）由 ModificationService.create_task 负责构造。

    original_text 不再是本模型的字段——它必须由服务端用 contract_id +
    clause_id 从 ContractManager 查出真实原文，绝不信任客户端传入的值
    （本次改动的硬约束，见 ModificationService.create_task 的说明）。

    batch_id 是新增的必填字段：每条任务必须显式归属一个已经存在的
    ModificationBatch（先调用 POST /modification-batches 开启一轮修改），
    不再有"默认 batch"、不再靠猜测归属。
    """

    batch_id: str = Field(..., min_length=1)
    clause_id: str = Field(..., min_length=1)
    lawyer_instruction: str = Field(..., min_length=1)


class ContractTextResponse(BaseModel):
    """GET /contracts/{contract_id}/text 的响应体。

    特意不直接返回裸字符串——和项目里其他读取接口（Clause/ReviewRecord 等）
    一样，返回一个带 contract_id 的 JSON 对象，前端按字段名取值，不用去猜
    "返回的到底是不是这份合同的文本"。这是一个通用的"读取某份合同已保存的
    完整解析文本"接口，不区分 V1/V2——任何 contract_id（无论是用户上传的
    合同，还是某个版本的 linked_contract_id）都能用同一个接口读。
    """

    contract_id: str
    text: str


@router.get("", response_model=list[Contract], status_code=status.HTTP_200_OK)
def list_contracts(
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> list[Contract]:
    """列出合同库中的全部合同（合同库页面用）。

    直接调用 ContractManager.list_contracts，不做分页、排序以外的任何加工——
    排序（按创建时间从新到旧）本身也是 ContractManager 的职责，本路由不重复
    实现。本阶段不支持删除/搜索/筛选，所以这里没有任何查询参数。

    exclude_version_hosts=True：只让"合同库"这一个列表排除 V2（将来 V3……）
    的数据宿主——生成版本时用的是和用户上传完全相同的 create_contract 入口
    （见 app/v2_generation_service.py），所以它们在存储层确实是
    "合法的 Contract"，只是不应该在合同库里被当成用户自己上传的独立合同
    展示。这个过滤只影响本路由；get_contract/clauses/review/text/diff 等
    其他读取合同数据的路由都不传这个参数，继续原样读取 V2 自己的数据
    （它们本来就需要能正常访问 V2，不能被这个过滤影响）。
    """
    return contract_service.list_contracts(exclude_version_hosts=True)


@router.post("", response_model=Contract, status_code=status.HTTP_201_CREATED)
def create_contract(
    file: UploadFile,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> Contract:
    """上传合同文件，创建一份新的合同记录。

    数据流：
        multipart/form-data 里的 UploadFile
          → 落到 <临时目录>/<原始文件名>
          → ContractManager.create_contract(临时文件路径)   —— 真正的业务逻辑
          → 删除整个临时目录（无论成功还是失败）
          → 返回 Contract

    临时文件为什么要保留原始文件名（而不是用随机文件名）：
        ContractManager.create_contract 把传入路径的 `.name` 原样记作
        Contract.filename、把 `.suffix` 判定为 file_format（见 infra/storage/manager.py）。
        如果临时文件用随机名字，保存下来的合同元数据里 filename 就会变成一串
        随机字符，而不是用户实际上传的文件名——所以这里选择"临时目录 + 原始
        文件名"的方案，而不是更常见的 tempfile.NamedTemporaryFile（随机名）。
        文件名只取 Path(...).name（不含任何目录部分），防止路径穿越。
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传请求缺少文件名",
        )

    safe_name = Path(file.filename).name  # 只取文件名部分，丢弃任何目录穿越尝试
    if not safe_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传请求缺少合法的文件名",
        )

    tmp_dir = tempfile.mkdtemp(prefix="contract_upload_")
    tmp_path = Path(tmp_dir) / safe_name
    try:
        with tmp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if tmp_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="上传的文件内容为空",
            )

        try:
            return contract_service.create_contract(tmp_path)
        except FileNotFoundError as exc:
            # 正常流程下不会发生（临时文件是我们自己刚写好的）；
            # 保留兜底处理，避免临时文件在极端情况下被外部删除时抛出未分类的 500。
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="临时文件处理失败",
            ) from exc
        except ContractError as exc:
            # 例如文件缺少有效扩展名——这是请求内容本身不合法，不是服务端错误。
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
    finally:
        file.file.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/{contract_id}/parse", response_model=list[Clause], status_code=status.HTTP_200_OK)
def parse_contract_route(
    contract_id: str,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> list[Clause]:
    """解析并切分一份已上传的合同，返回 Clause 列表。

    数据流：
        contract_id
          → document.preparation.parse_and_split_contract(contract_id, contract_manager)
            —— 解析原文 + 存 parsed_text.txt，再切分条款 + 存 clauses.json
          → 返回 clauses

    parse_and_split_contract 是 document.preparation 里的 Contract
    Preparation 能力（Review Workflow 的 Contract Loading 节点、
    ModificationService.generate_v2 复用的同一个函数），内部依次调用真实的
    DocumentParser 和 ClauseSplitter。本路由只负责调用它、把它抛出的异常
    映射成 HTTP 状态码，不重新实现解析或切分的任何逻辑，也不在这里判断
    "该合同能不能被解析"——这个判断完全交给 DocumentParser 自己的扩展名
    分发机制。

    （本路由函数之前与导入的编排函数同名，会在函数体内递归调用自己造成
    RecursionError——这是 Stage 1 遗留的一个潜在 bug，Stage 2 抽取
    Contract Preparation 能力时顺手改名修复，不再有命名冲突。）
    """
    try:
        return contract_service.parse_and_split(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except UnsupportedFormatError as exc:
        # UnsupportedFormatError 是 DocumentParseError 的子类，必须排在它前面。
        # 415：请求本身没问题，是这份文件的格式当前业务模块根本没有注册解析器。
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except NotImplementedError as exc:
        # pdf / docx / ocr 当前在 DocumentParser 里是"已注册但占位未实现"
        # （见 document/parser.py 的 PdfParser/DocxParser/OcrParser），
        # 对调用方来说同样是"这个格式现在解析不了"，同样映射成 415，
        # 不是服务端 bug，不应该是 500。
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"该文件格式的解析尚未实现：{exc}",
        ) from exc
    except DocumentParseError as exc:
        # 例如编码无法识别、解析不出任何文本——文件本身的内容有问题。
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/{contract_id}/clauses", response_model=list[Clause], status_code=status.HTTP_200_OK)
def get_contract_clauses(
    contract_id: str,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> list[Clause]:
    """读取某份合同已保存的 Clause 列表。

    直接调用 ContractManager.get_clauses，本路由不重新读取或解析 clauses.json，
    不做任何额外的业务判断。

    ContractManager.get_clauses 只检查 clauses.json 这个文件在不在，不关心
    背后的原因是"合同根本不存在"还是"合同存在但还没调用过 /parse"——这两种
    情况它抛出的是同一个 ContractNotFoundError。本路由如实反映这一点，不额外
    调用 get_contract() 去分辨这两种情况、伪造出两种不同的状态码，所以这里
    只有一种业务异常映射：404。
    """
    try:
        return contract_service.get_clauses(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        # clauses.json 存在但内容损坏（JSON 格式错误、字段校验失败）——
        # 这是服务端存储的数据出了问题，不是这次请求本身的错，映射成 500。
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/{contract_id}/text", response_model=ContractTextResponse, status_code=status.HTTP_200_OK)
def get_contract_text(
    contract_id: str,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> ContractTextResponse:
    """读取某份合同已保存的完整解析文本（parsed_text.txt）。

    通用接口，不写死只服务 V2：调用方传哪个 contract_id，就读哪份合同的
    原文——"这是 V1 自己的 contract_id 还是某个版本的 linked_contract_id"
    是调用方（前端"V2 原文"标签页会传 version.linked_contract_id）决定的，
    本路由和 ContractManager.get_parsed_text 都不知道、也不需要知道这一点，
    和项目里 Review/Diff 一直遵循的"V1/V2 对 Review 来说完全对等"是同一条
    架构约束。

    直接复用 ContractManager.get_parsed_text，不重新实现任何文件读取逻辑。
    先单独调用一次 get_contract 来区分两种 404：
        - 合同本身不存在（contract_id 格式不对，或目录/metadata.json 不存在）
        - 合同存在，但还没有解析过（没有 parsed_text.txt）
    这两种情况的报错信息不同，方便前端/调用者判断到底该怎么办（提示"合同
    不存在" vs 提示"还没有解析"），而不是像 get_clauses 那样统一成一种
    404——因为"V2 原文"这个场景下，"合同不存在"基本不该发生（V2 的
    contract_id 来自已经查到的 ContractVersion.linked_contract_id），区分
    开有助于一眼看出是不是出现了更严重的数据不一致。
    """
    try:
        contract_service.get_contract(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    try:
        text = contract_service.get_text(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return ContractTextResponse(contract_id=contract_id, text=text)


@router.post("/{contract_id}/review", response_model=ReviewReport, status_code=status.HTTP_200_OK)
def review_contract(
    contract_id: str,
    review_service: ReviewApplicationService = Depends(get_review_service),
) -> ReviewReport:
    """对一份已上传的合同发起一次完整审查，返回审查报告。

    数据流：
        contract_id
          → ReviewApplicationService.review(contract_id, save_result=True)
              —— Review Application：调用 Review Workflow（LangGraph 编排，
                 Contract Loading → LLM Review ∥ Rule Check → Merge →
                 Report Assembly，完全在 workflow/review_workflow.py 里）
                 拿到 ReviewReport，再按 save_result 决定要不要持久化
          → 返回（HTTP 200）

    本路由不再自己构造 ReviewReport、不再自己调用 contract_manager.
    save_review——这两步现在都在 ReviewApplicationService 里（见
    app/review_service.py），本路由只做"翻译 HTTP 请求 → 调用
    Application 服务 → 把异常映射成状态码"这一件事。

    本路由不改变 Review Workflow 既有的异常策略：Contract Loading、
    Rule Check、Merge、Report Assembly 里任何一步的异常，仍然会照常终止整张图
    并向上抛出（只有 LLM Review 对单条 Clause 的失败会被内部捕获进
    failed_clauses，这是 pipeline 自己的设计，不受本路由影响）；本路由只是
    把逃逸出来的异常映射成 HTTP 状态码，不新增重试、不降级、不吞掉。
    映射方式和 POST /parse 一致，因为 Contract Loading 节点内部调用的正是
    document.preparation.parse_contract / split_contract 这两个函数，会抛出
    同样几种异常。

    save_result 默认 True，和 Stage 1 时期"POST /review 总是落盘"的既有
    行为保持一致，历史审查记录不会被覆盖（见 ContractManager.save_review）。
    """
    try:
        return review_service.review(contract_id, save_result=True, contract_version="v1")
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except UnsupportedFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"该文件格式的解析尚未实现：{exc}",
        ) from exc
    except DocumentParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/{contract_id}/review", response_model=ReviewRecord, status_code=status.HTTP_200_OK)
def get_latest_review(
    contract_id: str,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> ReviewRecord:
    """取某份合同最近一次的审查记录（合同工作区"审查结果"页用）。

    直接调用 ContractManager.get_latest_review。合同不存在、或合同存在但
    从未审查过，都会得到同一个 ContractNotFoundError——和 GET /clauses 对
    "尚未切分"的处理方式保持一致，统一映射成 404，不在这里额外区分。
    """
    try:
        return contract_service.get_latest_review(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/{contract_id}/reviews", response_model=list[ReviewRecord], status_code=status.HTTP_200_OK)
def list_reviews(
    contract_id: str,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> list[ReviewRecord]:
    """列出某份合同的全部历史审查记录（"版本"页展示审查次数用，本阶段
    前端暂不展示完整历史内容，但接口按 ContractManager 的真实能力提供）。

    与 /clauses 不同：这里"合同存在但从未审查过"不是错误，是空列表——直接
    反映 ContractManager.list_reviews 的行为，本路由不重新定义语义。
    """
    try:
        return contract_service.list_reviews(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post(
    "/{contract_id}/modification-tasks",
    response_model=ModificationTask,
    status_code=status.HTTP_201_CREATED,
)
def create_modification_task(
    contract_id: str,
    payload: ModificationTaskCreate,
    modification_service=Depends(get_modification_service),
) -> ModificationTask:
    """创建一条修改任务：律师对某个条款提出修改意见，状态固定为 pending。

    数据流：contract_id + batch_id + clause_id + lawyer_instruction →
    ModificationService.create_task（校验批次存在且仍可接收新任务 →
    服务端查出条款原文、冻结当时的审查结果快照 → 冲突检测 → 持久化并把
    task_id 追加进批次）。本路由不再直接调用 ContractManager，所有业务
    规则（批次状态校验、冲突检测、原文/快照来源）都在 Service 层，本路由
    只负责把结果/异常翻译成 HTTP 响应。

    本路由仍然不做任何审批、不调用任何 LLM、不生成新版本合同——这些是
    "开始修改"（POST .../start）之后的事，创建任务本身只是记录律师的诉求。
    """
    try:
        return modification_service.create_task(
            contract_id=contract_id,
            batch_id=payload.batch_id,
            target_clause_id=payload.clause_id,
            lawyer_instruction=payload.lawyer_instruction,
        )
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ModificationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ModificationServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{contract_id}/modification-tasks",
    response_model=list[ModificationTask],
    status_code=status.HTTP_200_OK,
)
def list_modification_tasks(
    contract_id: str,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> list[ModificationTask]:
    """列出某份合同的全部修改任务（"修改任务"页用）。

    合同存在但还没有任何修改任务时返回空列表，不是错误——直接反映
    ContractManager.list_modification_tasks 的行为。
    """
    try:
        return contract_service.list_modification_tasks(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/{contract_id}", response_model=Contract, status_code=status.HTTP_200_OK)
def get_contract(
    contract_id: str,
    contract_service: ContractApplicationService = Depends(get_contract_service),
) -> Contract:
    """查询某份合同的元数据（当前处理到哪一步、文件信息等）。

    直接调用 ContractManager.get_contract，不重新拼装或计算任何字段。
    """
    try:
        return contract_service.get_contract(contract_id)
    except ContractNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ContractError as exc:
        # metadata.json 存在但内容损坏（JSON 格式错误、字段校验失败）——
        # 服务端存储的数据出了问题，不是这次请求本身的错，映射成 500。
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


