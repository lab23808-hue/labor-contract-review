# 测试分层说明

项目的测试分四层。前三层是 `pytest` 自动化测试，**不需要网络、不需要 API Key、不会下载模型**；
第四层是真实端到端验证，用脚本手动运行。

| 层 | pytest marker | 验证什么 | 外部服务 | 位置 |
|---|---|---|---|---|
| 单元测试 | `unit` | 单个函数/类的逻辑 | 全部 mock 或用假对象 | `tests/test_*.py`（见 `conftest.py`） |
| 模块测试 | `module` | 同一子系统里多个**真实**组件协作（真实 Chroma、真实文件系统上的 contract + parser + clause） | embedding 用假向量 | 同上 |
| LangGraph 流程测试 | `graph` | 真实 `langgraph` + 真实业务节点：并行、汇合、`failed_clauses`、异常向上抛出 | 只有 LLM 与检索用假对象 | `tests/test_review_pipeline.py` |
| 真实端到端 | （不在 pytest 里） | 真实合同 → 真实 BGE-M3 → 真实 Chroma → 真实 DeepSeek → 真实 LangGraph → LLM 分支 + 规则分支 → 汇合 → 最终报告 | **全部真实，不用任何 mock** | `scripts/verify_full_pipeline.py` |

## 运行

```bash
pytest                          # 前三层，全部
pytest -m unit                  # 只跑单元测试
pytest -m "unit or module"      # 不含 LangGraph 流程测试
pytest -m graph                 # 只跑 LangGraph 流程测试

python scripts/verify_full_pipeline.py            # 第四层：真实端到端（有 token 消耗）
```

第四层之外还有三个只验证局部链路的真实脚本，职责不同，互相不替代：

- `scripts/verify_rag_pipeline.py` / `scripts/verify_real_retrieval.py`：只验证检索
- `scripts/verify_review_pipeline.py`：只验证单条款 LLM 审查（不经过 LangGraph）
- `scripts/verify_rules_pipeline.py`：只验证 RuleChecker + 结果合并（不经过 LangGraph）

## 新增测试文件时

`tests/conftest.py` 里的 `TEST_LAYERS` 按文件名给测试自动打层级标记。**新文件必须在那里登记**，
否则收集阶段会报错提醒。

## 写测试时踩过的坑（都是"测试悄悄碰了真实环境"）

- 不要自己造一个"假的第三方 SDK 模块"再改它的属性：本地装了真 SDK 时那些改动根本不生效，
  测试会真的发出网络请求。要用 `unittest.mock.patch` 替换**被测模块里引用的那个名字**
  （例如 `patch("llm.client.OpenAI")`）。
- `HuggingFaceEmbeddings(...)` 在**构造时**就会加载/下载模型，不是懒加载：
  测 `build_embedder` 必须 `patch("rag.embedding.HuggingFaceEmbeddings")`。
- 读取 `.env` 的代码（`load_dotenv`）也要 mock（`patch("llm.client.load_dotenv")`），
  否则你本地真实的 `.env` 会把测试里刚删除的环境变量"补"回来。
- LangGraph 流程测试不断言引擎内部细节（比如节点执行顺序），只断言结果：
  两个分支都被调用、`final_results` 同时含 LLM 与规则结果——如果 merge 跑在某个分支之前，
  这些断言会失败。
