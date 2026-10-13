"""V2GenerationService：V2 生成的 Application 层（Part G）。

架构边界：这是本次改动从 modification/service.py::ModificationService.
generate_v2 里拆出来的一整块职责——"从一个已就绪的 ModificationBatch 生成
V2"本质上是一个独立于"修改闭环本身"的能力：它只在批次就绪之后被调用一次
（或在失败后重试），不参与 Task 的状态机，也不应该让 ModificationService
继续膀着这段逻辑（ModificationService 的生命周期现在明确止于
CONFIRMED/ABANDONED，见该文件的模块文档）。

V2 生成方式（与之前版本完全一致，算法本身未改动，只是调用入口从
contract_id 扫描全部任务，改成了 batch_id 精确限定一批任务）：
    以"条"为单位重建原文（document.reconstructor.build_v2_text /
    group_clauses_by_article，完全未改动），对批次里 CONFIRMED 的任务用
    current_modified_text 替换对应节点的区间，ABANDONED 的任务不放进
    modified_text_by_clause_id 映射——不替换就是"保留 V1 原文"，这是
    reconstruct_article_text 本来就有的行为（"没命中就直接从 V1 原始全文
    里取原样字符"），不需要给 ABANDONED 发明任何新逻辑。

批次状态流转（本文件负责维护，Part F）：
    IN_PROGRESS --(批次就绪)--> READY_FOR_V2 --generate--> V2_GENERATING
        --成功--> V2_GENERATED（generated_contract_id 被设置，不可再生成）
        --失败--> V2_FAILED（记录 last_error，可以重试：再次调用 generate
                   会重新进入 V2_GENERATING，成功后变为 V2_GENERATED，失败
                   再变回 V2_FAILED）
    一个批次只会成功生成一个 V2：V2_GENERATED 之后再次调用 generate 会被拒绝。

本文件不做的事：
    - 不重新实现 V2 全文重建算法本身（document.reconstructor 的纯函数职责）
    - 不碰 ModificationTask 的状态（CONFIRMED/ABANDONED 永久保留，不会变成
      任何"V2 完成"的状态）
    - 不做 HTTP
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from contract import ContractManager
from document.preparation import parse_and_split_contract
from document.reconstructor import build_v2_text, group_clauses_by_article
from modification.service import ModificationServiceError, compute_batch_readiness
from schemas import ContractVersion, ModificationBatchStatus
from schemas._time import utc_now

_TARGET_VERSION_NUMBER = "v2"


class V2GenerationService:
    def __init__(self, contract_manager: ContractManager) -> None:
        self.contract_manager = contract_manager

    def generate(self, contract_id: str, batch_id: str, created_by: str = "lawyer") -> ContractVersion:
        """从一个已就绪（或曾经失败、现在重试）的批次生成 V2。

        contract_id 必须是这个批次所属的（V1）合同；batch.source_contract_id
        和这里传入的 contract_id 不一致时拒绝，防止把一个批次的任务错误地
        拼接到另一份合同的全文上。
        """
        batch = self.contract_manager.get_batch(contract_id, batch_id)
        if batch.source_contract_id != contract_id:
            raise ModificationServiceError(f"批次 {batch_id} 不属于合同 {contract_id}")

        if batch.status == ModificationBatchStatus.V2_GENERATED:
            raise ModificationServiceError(f"批次 {batch_id} 已经成功生成过 V2（{batch.generated_contract_id}），不能重复生成")
        if batch.status == ModificationBatchStatus.V2_GENERATING:
            raise ModificationServiceError(f"批次 {batch_id} 正在生成 V2，不能重复触发")

        tasks = [self.contract_manager.get_modification_task(contract_id, tid) for tid in batch.task_ids]
        ready, blocking, confirmed = compute_batch_readiness(tasks)
        if not ready:
            if blocking:
                raise ModificationServiceError(
                    f"批次 {batch_id} 还有 {len(blocking)} 条修改任务未落入终态（pending/waiting_confirmation/"
                    "rejected/needs_human），不能生成 V2：请先确认或放弃全部任务。"
                )
            raise ModificationServiceError(f"批次 {batch_id} 没有任何已确认（confirmed）的修改任务，没有必要生成 V2")

        existing_versions = self.contract_manager.list_versions(contract_id)
        if any(v.version_number == _TARGET_VERSION_NUMBER for v in existing_versions):
            # 本阶段恒为 v1->v2 单一版本，ContractVersion.save_version 本身也会
            # 拒绝重复的 version_number；这里提前检查给出更贴合批次语境的报错。
            raise ModificationServiceError(f"合同 {contract_id} 已存在版本 {_TARGET_VERSION_NUMBER}，不能重复生成")

        batch.status = ModificationBatchStatus.V2_GENERATING
        batch.last_error = None
        batch.updated_at = utc_now()
        batch = self.contract_manager.update_batch(batch)

        try:
            version = self._do_generate(contract_id, confirmed, created_by)
        except Exception as exc:  # noqa: BLE001 - 失败必须被记录到批次上，不允许让批次停留在 V2_GENERATING
            batch = self.contract_manager.get_batch(contract_id, batch_id)
            batch.status = ModificationBatchStatus.V2_FAILED
            batch.last_error = str(exc)
            batch.updated_at = utc_now()
            self.contract_manager.update_batch(batch)
            raise ModificationServiceError(f"生成 V2 失败：{exc}") from exc

        batch = self.contract_manager.get_batch(contract_id, batch_id)
        batch.status = ModificationBatchStatus.V2_GENERATED
        batch.generated_contract_id = version.linked_contract_id
        batch.last_error = None
        batch.updated_at = utc_now()
        self.contract_manager.update_batch(batch)
        return version

    def _do_generate(self, contract_id: str, confirmed_tasks, created_by: str) -> ContractVersion:
        clauses = self.contract_manager.get_clauses(contract_id)
        full_text = self.contract_manager.get_parsed_text(contract_id)
        # ABANDONED 的任务不进入这个映射——对应 reconstruct_article_text
        # "没命中就直接从 V1 原始全文取原样字符"的既有行为，等价于"保留原文"，
        # 不需要为 ABANDONED 单独处理。
        modified_text_by_clause_id = {t.target_clause_id: t.current_modified_text for t in confirmed_tasks}

        article_groups = group_clauses_by_article(clauses)
        v2_text = build_v2_text(full_text, article_groups, modified_text_by_clause_id)

        tmp_dir = tempfile.mkdtemp(prefix="contract_v2_")
        tmp_path = Path(tmp_dir) / f"{contract_id}_v2.txt"
        # newline=""：见 docs/PITFALLS.md P-24，禁止平台相关的换行转换损坏原文。
        tmp_path.write_text(v2_text, encoding="utf-8", newline="")

        try:
            new_contract = self.contract_manager.create_contract(tmp_path)
            parse_and_split_contract(new_contract.contract_id, self.contract_manager)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
                Path(tmp_dir).rmdir()
            except OSError:
                pass  # 清理失败不影响主流程，临时目录留着不影响正确性

        version = ContractVersion(
            version_id=f"{contract_id}_{_TARGET_VERSION_NUMBER}",
            contract_id=contract_id,
            version_number=_TARGET_VERSION_NUMBER,
            source_version="v1",
            parent_contract_id=contract_id,  # 本阶段恒为 V1 自己的 contract_id（V1→V2）
            linked_contract_id=new_contract.contract_id,
            created_by=created_by,
        )
        return self.contract_manager.save_version(version)
