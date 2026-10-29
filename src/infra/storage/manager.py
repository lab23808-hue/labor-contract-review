"""ContractManager：合同文件的本地存储管理（不使用数据库）。

存储布局：
    <root_dir>/<contract_id>/
        original_file/<原始文件名>    原始合同文件（只写一次，不允许覆盖，是审计依据）
        parsed_text.txt               DocumentParser 解析出的原文（可重新解析、允许覆盖）
        clauses.json                  ClauseSplitter 切分出的 Clause 列表（可重新切分、允许覆盖）
        metadata.json                 Contract 对象序列化结果（最后写入）

只要 metadata.json 存在，就说明这份合同已完整创建；
创建过程中任何一步失败，都会清理掉整个合同目录，不留半成品。

本模块只负责“存”：不解析、不切分、不审查。
save_parsed_text 只是把已经解析好的文本存下来并把状态推进到 parsed，
文本本身由谁解析、怎么解析，本模块不关心（不依赖 parser 包）。
"""

import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional, Union

from config import settings
from core._time import utc_now
from core.clause import Clause
from core.contract import Contract, ContractStatus
from core.contract_version import ContractVersion
from core.modification_batch import ModificationBatch
from core.modification_task import ModificationTask, ReviewResultSnapshot
from core.review_record import ReviewRecord
from core.review_report import ReviewReport
from domain.ports import StorageError, StorageNotFoundError

# 默认存储根目录：见 config/settings.py 的 CONTRACTS_DIR（基于文件位置推导，不依赖当前工作目录）。
DEFAULT_ROOT_DIR = settings.CONTRACTS_DIR

_ORIGINAL_DIR = "original_file"
_PARSED_TEXT_FILE = "parsed_text.txt"
_CLAUSES_FILE = "clauses.json"
_METADATA_FILE = "metadata.json"
_REVIEW_DIR = "review"
_MODIFICATION_TASKS_DIR = "modification_tasks"
_MODIFICATION_BATCHES_DIR = "modification_batches"
_VERSIONS_DIR = "versions"

logger = logging.getLogger(__name__)

_CONTRACT_ID_RE = re.compile(r"[0-9a-f]{32}")  # uuid4().hex
_EXTENSION_RE = re.compile(r"[a-z0-9]+")  # 与 Contract.file_format 的约束一致
_CHUNK_SIZE = 1024 * 1024  # 计算哈希时每次读 1MB，避免大文件一次性读入内存


class ContractError(StorageError):
    """合同管理相关的错误基类。"""


class ContractNotFoundError(ContractError, StorageNotFoundError):
    """合同不存在（包括 contract_id 格式不合法、目录不完整）。"""


class ContractManager:
    """合同文件管理器。

    用法：
        manager = ContractManager()
        contract = manager.create_contract("data/samples/劳动合同.txt")
        same = manager.get_contract(contract.contract_id)
    """

    def __init__(self, root_dir: Union[str, Path, None] = None) -> None:
        self.root_dir = Path(root_dir) if root_dir is not None else DEFAULT_ROOT_DIR

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def create_contract(self, file_path: Union[str, Path]) -> Contract:
        """登记一份合同：生成 ID → 保存原始文件 → 计算 sha256 → 写入 metadata.json。

        - 同一个文件上传多次会得到多份独立的合同（不同 contract_id，相同 sha256）。
        - 源文件只被复制，不会被移动或修改。
        - 文件不存在（或是目录）抛 FileNotFoundError；扩展名缺失或不合法抛 ContractError。
        """
        source = Path(file_path)
        if not source.is_file():
            raise FileNotFoundError(f"合同文件不存在或不是文件：{source}")

        # Contract 需要知道文件格式，没有有效扩展名就无法登记
        file_format = source.suffix.lower().lstrip(".")
        if not _EXTENSION_RE.fullmatch(file_format):
            raise ContractError(f"文件缺少有效的扩展名：{source.name!r}")

        contract_id = uuid.uuid4().hex
        contract_dir = self.root_dir / contract_id
        contract_dir.mkdir(parents=True)  # 目录必须是新的；根目录不存在时一并创建

        try:
            saved = self.save_original_file(contract_id, source)
            contract = Contract(
                contract_id=contract_id,
                filename=source.name,
                file_format=file_format,
                sha256=_sha256_of(saved),  # 对保存后的副本计算，保证哈希对应存下来的内容
                size_bytes=saved.stat().st_size,
            )
            self._write_metadata(contract_dir, contract)
        except BaseException:
            shutil.rmtree(contract_dir, ignore_errors=True)  # 不留半成品
            raise
        return contract

    def get_contract(self, contract_id: str) -> Contract:
        """按 contract_id 读取合同信息。不存在抛 ContractNotFoundError，元数据损坏抛 ContractError。"""
        metadata_path = self._contract_dir(contract_id) / _METADATA_FILE
        if not metadata_path.is_file():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")
        try:
            return Contract.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        except ValueError as e:  # 包含 JSON 格式错误、字段校验失败、编码错误
            raise ContractError(f"合同元数据已损坏：{contract_id}") from e

    def list_contracts(self, exclude_version_hosts: bool = False) -> list[Contract]:
        """列出根目录下所有已完整创建的合同，按创建时间从新到旧排序。

        只依据 metadata.json 是否存在、是否能被正确解析来判断"这是不是一份
        合同"——和 get_contract 用的是同一个标准（见模块顶部说明："只要
        metadata.json 存在，就说明这份合同已完整创建"）。

        目录里出现的其他内容（半成品目录、非 contract_id 格式的杂项文件）
        直接跳过，不抛异常——列表接口本来就是"能读到多少算多少"，不应该
        因为个别脏数据让整个列表接口 500。metadata.json 存在但内容损坏的
        情况同样跳过（真正的损坏检测、修复不是列表接口的职责）。

        exclude_version_hosts（默认 False，不改变既有行为）：为 True 时，
        额外排除"是某个 ContractVersion.linked_contract_id 的合同"——这些
        合同是生成 V2（将来 V3……）时，用和用户上传完全相同的
        create_contract 入口创建出来的真实 Contract 实例（见
        app/v2_generation_service.py::_do_generate），数据本身完全
        合法、不会被本方法删除或改动，只是"合同库"这个列表语境下不应该把
        它们当成用户自己上传的独立合同来展示。

        这个过滤只依据已有的 ContractVersion 记录（不新增任何字段、不猜测
        文件名规律），逐个合同调用已有的 list_versions 收集
        linked_contract_id 集合：
            - 某个合同自己的版本记录读取失败（list_versions 可能抛出的
              ContractError 及其子类），只记录日志、跳过这一个合同的版本
              数据，不让整次 list_contracts 调用失败，也不会因为"读不到"
              就把任何合同误判为版本宿主——"确认不了"永远倒向"保留在列表
              里"，不会倒向"错误排除一份原始合同"。
            - 多条版本记录指向同一个 linked_contract_id（重复引用）、或者
              一份合同同时是另外两条版本记录的宿主，都只是在同一个 set 里
              出现多次，天然去重，不需要额外处理。
        """
        if not self.root_dir.is_dir():
            return []

        contracts: list[Contract] = []
        for entry in self.root_dir.iterdir():
            if not entry.is_dir() or not _CONTRACT_ID_RE.fullmatch(entry.name):
                continue
            metadata_path = entry / _METADATA_FILE
            if not metadata_path.is_file():
                continue
            try:
                contracts.append(Contract.model_validate_json(metadata_path.read_text(encoding="utf-8")))
            except ValueError:
                continue

        contracts.sort(key=lambda c: c.created_at, reverse=True)

        if not exclude_version_hosts:
            return contracts

        linked_contract_ids: set[str] = set()
        for contract in contracts:
            try:
                for version in self.list_versions(contract.contract_id):
                    linked_contract_ids.add(version.linked_contract_id)
            except ContractError as exc:
                # 某份合同自己的版本记录读不出来（损坏/格式错误），跳过它的
                # 版本数据继续处理其他合同——绝不能因为一条版本记录损坏，
                # 就让整个合同列表接口失败。
                logger.warning(
                    "list_contracts(exclude_version_hosts=True)：读取合同 %s 的版本记录失败，"
                    "跳过（不影响其他合同）：%s",
                    contract.contract_id,
                    exc,
                )
                continue

        return [c for c in contracts if c.contract_id not in linked_contract_ids]

    def save_original_file(self, contract_id: str, source_path: Union[str, Path]) -> Path:
        """把原始文件复制到 <合同目录>/original_file/ 下，保留原文件名，返回保存后的路径。

        原始文件只能保存一次，重复保存抛 ContractError（原件不可被覆盖）。
        合同目录不存在抛 ContractNotFoundError。
        """
        contract_dir = self._contract_dir(contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")

        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(f"合同文件不存在或不是文件：{source}")

        target_dir = contract_dir / _ORIGINAL_DIR
        try:
            target_dir.mkdir()
        except FileExistsError as e:
            raise ContractError(f"合同 {contract_id} 的原始文件已保存，不允许覆盖") from e

        target = target_dir / source.name  # .name 不含路径分隔符，不会写到目录之外
        try:
            shutil.copyfile(source, target)
        except BaseException:
            shutil.rmtree(target_dir, ignore_errors=True)  # 复制中途失败，不留残缺文件
            raise
        return target

    def get_original_file_path(self, contract_id: str) -> Path:
        """返回某份合同已保存的原始文件路径，供 DocumentParser 读取。

        本方法不知道、也不关心调用者会怎么解析这个文件。
        """
        contract_dir = self._contract_dir(contract_id)
        original_dir = contract_dir / _ORIGINAL_DIR
        if not original_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在或尚未保存原始文件：{contract_id}")

        files = [p for p in original_dir.iterdir() if p.is_file()]
        if len(files) != 1:
            # 正常流程下 original_file/ 里应当恰好一个文件；出现 0 个或多个说明目录被手动改动过
            raise ContractError(
                f"合同 {contract_id} 的 original_file 目录状态异常（应有且仅有 1 个文件，实际 {len(files)} 个）"
            )
        return files[0]

    def save_parsed_text(self, contract_id: str, text: str) -> Path:
        """保存 DocumentParser 的解析结果，并把合同状态推进到 parsed。

        与原始文件不同，parsed_text.txt 是可重新生成的派生数据，允许被覆盖
        （例如以后升级了 parser，需要用新逻辑重新解析）。
        写入用 newline=""，禁止 Python 的换行转换，保证存下来的内容与
        DocumentParser 返回的字符串逐字节一致（例如 CRLF 不会被改写）。
        """
        contract = self.get_contract(contract_id)  # 确认合同存在，并取得当前元数据
        contract_dir = self._contract_dir(contract_id)

        target = contract_dir / _PARSED_TEXT_FILE
        tmp = contract_dir / (_PARSED_TEXT_FILE + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        os.replace(tmp, target)

        data = contract.model_dump()
        data["status"] = ContractStatus.PARSED
        data["updated_at"] = utc_now()
        self._write_metadata(contract_dir, Contract(**data))
        return target

    def get_parsed_text(self, contract_id: str) -> str:
        """读回已保存的解析结果。尚未解析过时抛 ContractNotFoundError。"""
        path = self._contract_dir(contract_id) / _PARSED_TEXT_FILE
        if not path.is_file():
            raise ContractNotFoundError(f"合同 {contract_id} 尚未解析（没有 parsed_text.txt）")
        # Path.read_text() 不支持 newline 参数（只有 write_text 才有），改用 open()
        with path.open(encoding="utf-8", newline="") as f:
            return f.read()

    def save_clauses(self, contract_id: str, clauses: list[Clause]) -> Path:
        """保存 ClauseSplitter 的切分结果，并把合同状态推进到 split。

        与 parsed_text.txt 一样，clauses.json 是可重新生成的派生数据，允许被覆盖
        （例如以后升级了切分逻辑，需要重新切分）。

        保存前会校验每个 Clause 的 contract_id 都等于本次操作的 contract_id，
        防止调用方传错列表、把 A 合同的条款存进 B 合同的目录。
        """
        contract = self.get_contract(contract_id)  # 确认合同存在，并取得当前元数据
        contract_dir = self._contract_dir(contract_id)

        mismatched = [c.clause_id for c in clauses if c.contract_id != contract_id]
        if mismatched:
            raise ContractError(
                f"以下 Clause 的 contract_id 与目标合同 {contract_id} 不一致，拒绝保存：{mismatched}"
            )

        payload = json.dumps([c.model_dump(mode="json") for c in clauses], ensure_ascii=False, indent=2)
        target = contract_dir / _CLAUSES_FILE
        tmp = contract_dir / (_CLAUSES_FILE + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)

        data = contract.model_dump()
        data["status"] = ContractStatus.SPLIT
        data["updated_at"] = utc_now()
        self._write_metadata(contract_dir, Contract(**data))
        return target

    def get_clauses(self, contract_id: str) -> list[Clause]:
        """读回已保存的 Clause 列表。尚未切分过时抛 ContractNotFoundError。"""
        path = self._contract_dir(contract_id) / _CLAUSES_FILE
        if not path.is_file():
            raise ContractNotFoundError(f"合同 {contract_id} 尚未切分（没有 clauses.json）")
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
            return [Clause(**item) for item in items]
        except ValueError as e:  # JSON 格式错误、字段校验失败
            raise ContractError(f"合同 {contract_id} 的 Clause 数据已损坏") from e

    def load_clauses(self, contract_id: str) -> Optional[list[Clause]]:
        """读取已保存的 Clause；不存在时返回 None，数据损坏仍抛 ContractError。"""
        try:
            return self.get_clauses(contract_id)
        except ContractNotFoundError:
            return None

    def save_review(self, contract_id: str, report: ReviewReport, contract_version: str = "v1") -> ReviewRecord:
        """持久化一次审查结果，并把合同状态推进到 reviewed。

        与 parsed_text.txt / clauses.json 不同，审查记录【不可覆盖】——
        每次调用都新增一个 review_<review_id>.json，历史审查结果永久保留
        （见需求："历史审查结果不能被覆盖"）。review_id 按"合同版本"内的
        顺序编号（v1_001、v1_002……、v2_001、v2_002……）。

        contract_version 由调用方显式传入（P-22 修复前这里曾经硬编码
        "v1"，导致 V1、V2 各自第一次保存的 review 都被编号成 "v1_001"，
        字符串巧合相同、极具误导性，见 docs/PITFALLS.md）：
            - api/routes/contracts.py（通过 ReviewApplicationService）对 V1
              自己的 contract_id 调用时传 "v1"；
            - api/routes/modification.py::run_version_review（通过
              ReviewApplicationService.review_and_save）对 V2 的内部
              linked_contract_id 调用时传 "v2"。
        本方法不从 contract_id 猜版本——两个内部 contract_id 在数据结构上
        完全对等，唯一知道"这次存的是 V1 还是 V2"的是调用方，所以版本必须
        由调用方显式声明。同一份合同的 review 已经按 contract_id 隔离在
        各自的目录里，这个参数只影响目录内 review_id 的展示字符串，不影响
        存到了哪个目录——风险 Diff（app/diff_service.py::
        DiffApplicationService.risk_diff）判断"这是不是 V2 的记录"，依据的
        是"从哪个 contract_id 的 review 目录读出来的"，不是 review_id
        字符串前缀。
        """
        contract = self.get_contract(contract_id)  # 确认合同存在，并取得当前元数据
        contract_dir = self._contract_dir(contract_id)

        review_dir = contract_dir / _REVIEW_DIR
        review_dir.mkdir(exist_ok=True)

        existing = list(review_dir.glob(f"review_{contract_version}_*.json"))
        review_id = f"{contract_version}_{len(existing) + 1:03d}"

        record = ReviewRecord(
            review_id=review_id,
            contract_id=contract_id,
            contract_version=contract_version,
            report=report,
        )

        target = review_dir / f"review_{review_id}.json"
        tmp = review_dir / f"review_{review_id}.json.tmp"
        tmp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, target)

        data = contract.model_dump()
        data["status"] = ContractStatus.REVIEWED
        data["updated_at"] = utc_now()
        self._write_metadata(contract_dir, Contract(**data))
        return record

    def list_reviews(self, contract_id: str) -> list[ReviewRecord]:
        """按生成时间从旧到新列出某份合同的全部历史审查记录。

        合同不存在抛 ContractNotFoundError；合同存在但从未审查过，返回空列表
        （不是错误——这是"还没做过审查"的正常状态，和 get_clauses 对"尚未
        切分"统一按 ContractNotFoundError 处理不同：审查历史为空本来就是
        合理状态，不需要用异常表达）。
        """
        contract_dir = self._contract_dir(contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")

        review_dir = contract_dir / _REVIEW_DIR
        if not review_dir.is_dir():
            return []

        records = []
        for path in sorted(review_dir.glob("review_*.json")):
            try:
                records.append(ReviewRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError as e:
                raise ContractError(f"合同 {contract_id} 的审查记录已损坏：{path.name}") from e

        records.sort(key=lambda r: r.created_at)
        return records

    def get_latest_review(self, contract_id: str) -> ReviewRecord:
        """取某份合同最近一次的审查记录。

        合同不存在抛 ContractNotFoundError；合同存在但从未审查过，同样抛
        ContractNotFoundError——对调用方（API 层）来说，"这份合同没有审查
        记录可看"和"这份合同不存在"都应该得到 404，处理方式和 get_clauses
        对"尚未切分"的处理保持一致，不额外发明新的状态码含义。
        """
        records = self.list_reviews(contract_id)
        if not records:
            raise ContractNotFoundError(f"合同 {contract_id} 尚未生成过审查报告")
        return records[-1]

    def get_review(self, contract_id: str, review_id: str) -> ReviewRecord:
        """按 review_id 取某一次具体的历史审查记录（不一定是最新一次）。

        创建 ModificationTask 时需要冻结"任务创建时那一次审查"的快照
        （source_review_snapshot），不能总是假设"任务是针对最新一次审查
        提出的"——合同有可能在任务创建之后又被重新审查过。不存在抛
        ContractNotFoundError，与本类其余"找不到就是 404"的约定一致。
        """
        for record in self.list_reviews(contract_id):
            if record.review_id == review_id:
                return record
        raise ContractNotFoundError(f"合同 {contract_id} 不存在审查记录：{review_id}")

    def create_modification_task(
        self,
        contract_id: str,
        clause_id: str,
        original_text: str,
        lawyer_instruction: str,
        batch_id: str,
        source_review_id: str,
        source_review_snapshot: ReviewResultSnapshot,
    ) -> ModificationTask:
        """创建一条修改任务（律师对某个条款提出的修改意见），状态固定为 pending。

        本方法只负责"存"：不校验 clause_id 是否真的存在于当前 clauses.json
        里、不校验 batch_id 对应的批次是否存在/处于可接收新任务的状态——这些
        校验属于 modification/service.py::ModificationService.create_task
        （编排层），本方法不重复做；original_text 必须是调用方已经从
        ContractManager 查出的真实条款原文（不是客户端直接传入的值），
        source_review_snapshot 必须是调用方已经冻结好的快照，本方法只管
        原样存下去。
        """
        contract = self.get_contract(contract_id)  # 确认合同存在
        contract_dir = self._contract_dir(contract_id)

        tasks_dir = contract_dir / _MODIFICATION_TASKS_DIR
        tasks_dir.mkdir(exist_ok=True)

        existing = list(tasks_dir.glob("task_*.json"))
        task_id = f"task_{len(existing) + 1:03d}"

        task = ModificationTask(
            task_id=task_id,
            contract_id=contract.contract_id,
            batch_id=batch_id,
            source_review_id=source_review_id,
            source_review_snapshot=source_review_snapshot,
            target_clause_id=clause_id,
            original_text=original_text,
            lawyer_instructions=[lawyer_instruction],
        )

        self._write_modification_task(tasks_dir, task)
        return task

    def list_modification_tasks(self, contract_id: str) -> list[ModificationTask]:
        """按创建顺序列出某份合同的全部修改任务。合同不存在抛 ContractNotFoundError；
        合同存在但还没有任何修改任务，返回空列表（不是错误）。
        """
        contract_dir = self._contract_dir(contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")

        tasks_dir = contract_dir / _MODIFICATION_TASKS_DIR
        if not tasks_dir.is_dir():
            return []

        tasks = []
        for path in sorted(tasks_dir.glob("task_*.json")):
            try:
                tasks.append(ModificationTask.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError as e:
                raise ContractError(f"合同 {contract_id} 的修改任务数据已损坏：{path.name}") from e
        return tasks

    def get_modification_task(self, contract_id: str, task_id: str) -> ModificationTask:
        """读取单条修改任务。合同不存在、或该任务不存在，都抛 ContractNotFoundError
        （和本项目里"找不到就是 404"的一贯处理方式保持一致）。
        """
        contract_dir = self._contract_dir(contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")

        task_path = contract_dir / _MODIFICATION_TASKS_DIR / f"{task_id}.json"
        if not task_path.is_file():
            raise ContractNotFoundError(f"合同 {contract_id} 不存在修改任务：{task_id}")
        try:
            return ModificationTask.model_validate_json(task_path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ContractError(f"合同 {contract_id} 的修改任务数据已损坏：{task_id}") from e

    def update_modification_task(self, task: ModificationTask) -> ModificationTask:
        """把一条修改任务的最新状态整体写回磁盘（Modification Agent 工作流里
        任务状态流转、追加 modification_attempts 都通过这个方法持久化）。

        和创建时一样"先写临时文件再改名"，避免读到写了一半的文件；
        task.task_id 决定写到哪个文件，本方法不生成新 id、不检查任务是否
        已存在——调用方（modification/service.py）负责先 get_modification_task
        拿到当前版本、在内存里修改后再调用本方法整体替换。
        """
        contract_dir = self._contract_dir(task.contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{task.contract_id}")

        tasks_dir = contract_dir / _MODIFICATION_TASKS_DIR
        tasks_dir.mkdir(exist_ok=True)
        self._write_modification_task(tasks_dir, task)
        return task

    @staticmethod
    def _write_modification_task(tasks_dir: Path, task: ModificationTask) -> None:
        target = tasks_dir / f"{task.task_id}.json"
        tmp = tasks_dir / f"{task.task_id}.json.tmp"
        tmp.write_text(task.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, target)

    # ------------------------------------------------------------------
    # ModificationBatch 持久化（与 ModificationTask 完全相同的存储模式：
    # 独立 JSON 文件，存在【原合同】目录下，先写临时文件再改名）
    # ------------------------------------------------------------------

    def create_batch(self, contract_id: str, source_review_id: str) -> ModificationBatch:
        """创建一个新的修改批次（律师显式"开始一轮修改"），状态固定为 in_progress。

        本方法不校验 source_review_id 对应的审查记录是否存在——那是
        modification/service.py::ModificationService.create_batch 的职责
        （编排层负责校验，Storage 层只管存）。
        """
        contract = self.get_contract(contract_id)  # 确认合同存在
        contract_dir = self._contract_dir(contract_id)

        batches_dir = contract_dir / _MODIFICATION_BATCHES_DIR
        batches_dir.mkdir(exist_ok=True)

        existing = list(batches_dir.glob("batch_*.json"))
        batch_id = f"batch_{len(existing) + 1:03d}"

        batch = ModificationBatch(
            batch_id=batch_id,
            source_contract_id=contract.contract_id,
            source_review_id=source_review_id,
        )
        self._write_modification_batch(batches_dir, batch)
        return batch

    def list_batches(self, contract_id: str) -> list[ModificationBatch]:
        """按创建顺序列出某份合同的全部修改批次。合同不存在抛
        ContractNotFoundError；合同存在但还没有任何批次，返回空列表。
        """
        contract_dir = self._contract_dir(contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")

        batches_dir = contract_dir / _MODIFICATION_BATCHES_DIR
        if not batches_dir.is_dir():
            return []

        batches = []
        for path in sorted(batches_dir.glob("batch_*.json")):
            try:
                batches.append(ModificationBatch.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError as e:
                raise ContractError(f"合同 {contract_id} 的修改批次数据已损坏：{path.name}") from e
        return batches

    def get_batch(self, contract_id: str, batch_id: str) -> ModificationBatch:
        """读取单个修改批次。合同不存在、或该批次不存在，都抛 ContractNotFoundError。"""
        contract_dir = self._contract_dir(contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")

        batch_path = contract_dir / _MODIFICATION_BATCHES_DIR / f"{batch_id}.json"
        if not batch_path.is_file():
            raise ContractNotFoundError(f"合同 {contract_id} 不存在修改批次：{batch_id}")
        try:
            return ModificationBatch.model_validate_json(batch_path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ContractError(f"合同 {contract_id} 的修改批次数据已损坏：{batch_id}") from e

    def update_batch(self, batch: ModificationBatch) -> ModificationBatch:
        """把一个修改批次的最新状态整体写回磁盘。调用方负责先 get_batch
        拿到当前版本、在内存里修改后再调用本方法整体替换（与
        update_modification_task 的用法完全一致）。
        """
        contract_dir = self._contract_dir(batch.source_contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{batch.source_contract_id}")

        batches_dir = contract_dir / _MODIFICATION_BATCHES_DIR
        batches_dir.mkdir(exist_ok=True)
        self._write_modification_batch(batches_dir, batch)
        return batch

    @staticmethod
    def _write_modification_batch(batches_dir: Path, batch: ModificationBatch) -> None:
        target = batches_dir / f"{batch.batch_id}.json"
        tmp = batches_dir / f"{batch.batch_id}.json.tmp"
        tmp.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def save_version(self, version: ContractVersion) -> ContractVersion:
        """保存一条 ContractVersion 记录（本阶段实际只会是 V2）。

        存在【原合同】（version.contract_id）的目录下，永久保留、不覆盖已有
        版本记录——重复调用同一个 version_number 会抛 ContractError，
        避免意外覆盖已经生成的版本映射关系。
        """
        contract_dir = self._contract_dir(version.contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{version.contract_id}")

        versions_dir = contract_dir / _VERSIONS_DIR
        versions_dir.mkdir(exist_ok=True)

        target = versions_dir / f"version_{version.version_number}.json"
        if target.is_file():
            raise ContractError(f"合同 {version.contract_id} 已存在版本 {version.version_number}，不允许覆盖")

        tmp = versions_dir / f"version_{version.version_number}.json.tmp"
        tmp.write_text(version.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, target)
        return version

    def list_versions(self, contract_id: str) -> list[ContractVersion]:
        """列出某份合同的全部非 V1 版本记录（V1 是隐式的，不在这个列表里）。
        合同不存在抛 ContractNotFoundError；还没有生成过任何版本时返回空列表。
        """
        contract_dir = self._contract_dir(contract_id)
        if not contract_dir.is_dir():
            raise ContractNotFoundError(f"合同不存在：{contract_id}")

        versions_dir = contract_dir / _VERSIONS_DIR
        if not versions_dir.is_dir():
            return []

        versions = []
        for path in sorted(versions_dir.glob("version_*.json")):
            try:
                versions.append(ContractVersion.model_validate_json(path.read_text(encoding="utf-8")))
            except ValueError as e:
                raise ContractError(f"合同 {contract_id} 的版本数据已损坏：{path.name}") from e
        return versions

    def get_version(self, contract_id: str, version_number: str) -> ContractVersion:
        """取某一个具体版本的记录（例如 "v2"）。不存在抛 ContractNotFoundError。"""
        for version in self.list_versions(contract_id):
            if version.version_number == version_number:
                return version
        raise ContractNotFoundError(f"合同 {contract_id} 不存在版本：{version_number}")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _contract_dir(self, contract_id: str) -> Path:
        """合同目录路径。先校验 ID 格式：contract_id 以后会来自 API，不能让 '../' 之类穿出根目录。"""
        if not isinstance(contract_id, str) or not _CONTRACT_ID_RE.fullmatch(contract_id):
            raise ContractNotFoundError(f"合同不存在：{contract_id!r}")
        return self.root_dir / contract_id

    @staticmethod
    def _write_metadata(contract_dir: Path, contract: Contract) -> None:
        """先写临时文件再改名，避免读到写了一半的 metadata.json。"""
        final_path = contract_dir / _METADATA_FILE
        tmp_path = contract_dir / (_METADATA_FILE + ".tmp")
        tmp_path.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, final_path)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
