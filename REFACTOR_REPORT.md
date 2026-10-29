# REFACTOR_REPORT

基线：`pre-refactor` tag（commit `623a637`）。  
本次按计划顺序完成 P0-1 → P2-4，每个任务单独 commit，最终 `pytest` **386 passed**。

## 完成情况

| 任务 | commit | 实际改动 |
|---|---|---|
| P0-1 | `73707fb` | 新增 `KnowledgeLoader.count_evidences`；构建脚本整体删除 `data/index/chroma` 后重建并校验 count；dense/hybrid 启动校验；新增 `make build-kb` |
| P0-2 | `5588679` | `ReviewResult.evidences`；review 结果携带 Evidence；State 增加 `retrieval_results`/`retrieval_errors`；`ReviewVersions` 填入 model/prompt/ruleset/KB version；Prompt 要求引用 provided Evidence |
| P0-3 | `31ba053` | `ContractManager.load_clauses`；`contract_loading` 优先复用 `clauses.json`，缺失才解析 |
| P1-1 | `704a6e0` | 新增 `domain/ports.py`（LLMPort/StoragePort/端口错误）；domain/workflow 去掉 `from infra`；infra 异常继承端口错误 |
| P1-2 | `c7c2494` | 新增 `app/contract_service.py`、`api/errors.py`；路由改为调用 application service，不再 import domain/infra；版本解析下沉到 `ReviewApplicationService.review_version` |
| P1-3 | `9976b04` | `RETRIEVAL_STRATEGY` 支持环境变量；新增 `retrieve` 节点；`llm_review` 只消费 `retrieval_results`；单条检索失败单独记录 |
| P2-1 | `786ae30` | 恢复 `generate_eval_contracts.py`、`run_eval_samples.py`；新增 `evaluation/metrics.py`；生成 50 份评估合同；写入 `docs/EVAL_REPORT.md` |
| P2-2 | `68dc62c` | 新增 `retrieval/fusion.py`、`HybridBackend`；支持 hybrid 策略；BM25 过滤 0 分；追加三策略对比 |
| P2-3 | `ef3be5b` | 清理 docstring 漂移；新增 `docs/architecture.md`、4 个 ADR；`VERSION` 更新为 `kb-2026-10-29-01` |
| P2-4 | `7c4e271` | 新增 ModificationService/V2 测试；LLM timeout 配置（`LLM_TIMEOUT_SECONDS=60`，chat/tool 调用传入）与测试 |

## 验收结果

- `pytest`：**386 passed, 1 warning**。
- `grep -rn "from infra" src/domain src/workflow`：**0**。
- `grep -rn "from domain\|from infra" src/api/routes`：**0**。
- `data/index/chroma`：collection `legal_knowledge`，dimension `1024`，**count=32**。
- BM25：**32** 文档。
- `data/knowledge/VERSION`：`kb-2026-10-29-01`。
- 三策略评估（10 份合同，fake LLM）：
  - BM25 Recall@5 0.8667 / MRR@5 0.6650
  - Dense 1.0000 / 0.6343
  - Hybrid 1.0000 / 0.6994

## 偏离清单

1. **P1-3 State 增加 `retrieval_errors`**：计划只要求 `retrieval_results`。为保持“单条检索失败不终止整图”的既有语义，额外记录每条检索错误，`llm_review` 将其写入 `failed_clauses`。
2. **P1-2 路由仍保留部分 try/except**：异常类统一从 `api/errors.py` 导入，且 `install_exception_handlers` 已注册；路由里已有的状态码映射未全部删除，以避免改变测试契约。
3. **P1-1 infra 反向依赖 domain.ports**：`infra.storage`/`infra.llm` 的异常继承 `domain.ports` 的端口错误。这符合“适配器实现端口”的方向，但严格意义上 infra 仍 import domain；计划验收只要求 domain/workflow 不 import infra。
4. **P0-1 重建前备份**：本次先 `mv data/index/chroma data/index/chroma.pre-p0-1`，重建成功后删除备份；最终目录无备份。
5. **P2-2 三策略对比使用前 10 份合同**：全量 50 份的 Dense/Hybrid 未运行（成本/时间），50 份 BM25 数字保留。对比表明确标注样本为 10。
6. **P2-1 LLM 指标是 fake LLM**：fake LLM 恒返回 none，LLM 一致率不代表真实模型质量；EVAL_REPORT 已注明。
7. **P2-4 未新增完整修改/版本路由 pytest**：已覆盖 ModificationService/V2 服务层与现有 batch/task 路由；单独为 start/confirm/reject/abandon/versions/diff 路由构造完整 V2 数据成本较高，留作后续测试扩展。
8. **LLM timeout 代码落在 P2-3 commit**：settings/client 的 timeout 改动与 P2-3 文档修改同批提交；P2-4 commit 只包含对应测试。功能已完成，提交粒度有偏差。
9. **P2-3 部分历史 docstring 仍有“历史记录”措辞**：已删除失效路径，但部分历史背景说明保留，不影响当前路径。

## 遗留问题

- `ReviewResult.evidences` 已保存，但 `legal_basis` 仍只做 Prompt 约束，没有程序化逐字引用校验。
- `docs/EVAL_REPORT.md` 的 Dense/Hybrid 对比仅 10 份合同，需要更多样本复核。
- 修改/版本/Diff 路由仍缺完整 pytest 覆盖。
- `data/index/chroma` 是本地派生数据，未纳入 Git；换机器需重新 `make build-kb`。
