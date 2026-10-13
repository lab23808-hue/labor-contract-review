# 个人能力现状与知识缺口（CAPABILITY_GAPS）

> 本文件是本次知识库整理（2026-09-29）新建的独立文档，被 `docs/PROJECT_KNOWLEDGE.md` 引用。
> 原则：只写**有证据**的内容——证据来自本项目里真实写过的代码、真实修复过的 bug、真实运行过的验证。不臆测能力，不做泛泛的自我评价。没有证据支撑的一律标注"证据不足，暂不评级"。

## 一、已经实际接触并使用（有代码/测试/脚本证据）

| 技术 | 证据 |
|---|---|
| Pydantic v2 | `schemas/` 全部模型使用 `field_validator`/`model_validator`；`ReviewResult`/`Clause`/`Contract` 的字段一致性校验 |
| FastAPI | `api/app.py`/`api/dependencies.py`（`lifespan`+`Depends`+`app.state`）/`api/routes/*` 的完整实现，含依赖注入 bug 的真实定位与修复（P-20） |
| LangChain（部分组件） | `langchain_core.embeddings.Embeddings` 接口、`HuggingFaceEmbeddings`、`RecursiveCharacterTextSplitter` 的实际使用（`clause/clause_splitter.py`、`rag/embedding.py`） |
| LangGraph | `review/pipeline.py::build_graph`（真实 `StateGraph`，6 字段 State、5 Node、7 Edge），12 个 graph 测试在真实 LangGraph 1.2.12 上通过 |
| RAG（检索增强生成） | `rag/` 全部模块，真实 BGE-M3+Chroma 检索验证（三个 query 第一名全部命中） |
| Chroma（向量数据库） | `rag/database.py::ChromaKnowledgeBase`，真实持久化写入与检索 |
| Embedding（BGE-M3） | 真实模型加载、归一化向量、真实检索结果（distance 数值） |
| Function Calling | `modification/agent.py`/`llm/client.py::chat_with_tool`，真实 `tools`+`tool_choice` 参数，真实 DeepSeek 联调暴露并修复过一次真实限制（P-21：Thinking 模式与强制 tool_choice 冲突） |
| Human-in-the-loop（HITL） | `modification/service.py` 的完整状态机（pending/reviewing/rejected/needs_human/confirmed/completed），API 层的 confirm/reject 端点 |
| 依赖注入生命周期管理 | P-20 的完整定位与修复过程（单例 vs 现场组装的判断标准） |
| React（函数组件+Hooks） | `frontend/src/App.jsx` 的 `useState`/`useEffect` 状态管理，多个受控组件的 props/回调设计 |
| 文件系统持久化设计 | `contract/manager.py` 的原子写入（临时文件+`os.replace`）、路径穿越防护、状态机管理 |
| pytest 测试分层 | `tests/` 目录的 unit/module/graph 三层设计，298 个测试函数（本次整理实测），含 mock/真实依赖的边界处理 |
| Mock 与真实依赖的区分 | P-01 的四个真实案例（假 openai 模块失效、HuggingFaceEmbeddings 构造即加载、load_dotenv 读到真实 key、LangGraph 替身局限） |
| Git/文档化开发流程 | `docs/DEVLOG.md`/`docs/PITFALLS.md` 等文档本身就是"按真实开发过程记录"的证据 |

## 二、已接触但理解可能不完整（有部分证据，但不足以说"已掌握"）

| 技术 | 证据与局限 |
|---|---|
| LangChain 的 Chain/Agent 抽象 | 只用到 `Embeddings` 接口和 `RecursiveCharacterTextSplitter` 两个组件；**没有证据**表明使用过 `LangChain` 的 `AgentExecutor`/`Chain`/`Tool` 抽象——本项目的 Modification Agent 是直接基于 OpenAI SDK 的 `chat.completions.create(tools=...)` 手写的，不是 LangChain 的 Agent 框架 |
| LangGraph 的进阶能力 | State/Node/Edge/并行/汇合有真实使用证据；`conditional edges`/`reducer`/`retry`/`checkpoint`/`streaming` **完全没有使用过**，只在文档里讨论过"未来可能怎么用"，没有实现过 |
| React 生态的进阶部分 | 没有使用路由（React Router）、没有状态管理库（Redux/Zustand）、没有使用 TypeScript；组件设计是"props drilling"式的，没有 Context API 的使用证据 |
| 向量检索的进阶技术 | 只用了稠密向量+归一化的基础检索；稀疏检索、多向量混合检索、重排序（rerank）**没有实现过**，只在文档里提到"可以评估" |
| 多 Agent 协作 | 本项目只有单一职责的两个"Agent 角色"（ClauseReviewer 不算 Agent，ModificationAgent 是），**没有证据**表明接触过多 Agent 之间协作、通信的场景 |

## 三、当前明显知识缺口（有真实影响，需要后续学习）

| 缺口 | 为什么影响当前项目 | 后续是否应该学习 | 最好通过什么项目场景学习 |
|---|---|---|---|
| LangGraph 条件边/重试/checkpoint | 当前 Review Pipeline 的失败处理是"整图终止"，无法优雅处理"部分节点失败、其余继续"的场景；Modification 链路完全没有用 LangGraph（是手写的状态机） | 是——这是简历上写"熟悉 LangGraph"最容易被追问、也最容易露怯的地方 | 给 Modification 链路本身建一张小的 LangGraph 图（Agent 调用→Validator→根据结果走不同边），比在 Review 主图上硬加更安全，也更贴近"条件路由"的真实使用场景 |
| Agent 的多工具选择与自主规划 | Modification Agent 目前只有一个工具，"Tool Selection"这个能力完全没有被验证过；如果面试官问"如果有 5 个工具，模型选错了怎么办"，目前没有真实经验可以回答 | 是 | 给 Modification 增加第二个工具（例如"新增条款"），观察真实的工具选择准确率、模型混淆两个工具的真实概率 |
| 自动化测试对 Agent/LLM 逻辑的覆盖 | Modification 模块目前完全没有 `tests/test_modification*.py`，只有手工运行的 `scripts/verify_*.py`（详见 `docs/DEVELOPMENT_LOG.md` 3.14 遗留问题） | 是——这是一个可以立刻动手补的、性价比很高的缺口 | 直接在本项目里补：用 mock 的 `llm_client` 写 `ModificationAgent`/`ModificationService` 的单元测试，覆盖状态机的全部转移路径 |
| 跨平台 I/O 的系统性认知 | P-24（换行符损坏）说明对 `open()`/`write_text()` 的 `newline` 参数语义、`os.linesep` 的平台差异这类"看起来是小细节，实际是系统性知识"的内容，是靠真实踩坑才学到的，不是提前系统学过 | 是 | 不需要专门项目，读一遍 Python 官方文档 `io` 模块和 `os.linesep` 的说明，再检查项目里所有"写文件"的地方是否都显式声明了 `newline` |
| 向量检索的评估方法论 | 目前"检索效果好不好"完全靠人工观察几个 query 的 `distance` 排序，没有系统性的评估指标（Recall@K、MRR 等） | 是——如果知识库规模扩大，靠人工观察会不可持续 | 找一个有标注数据的检索评估任务练手，再回来给本项目的知识库加一套评估脚本 |
| SQLite/关系型数据库设计 | 当前用文件系统 JSON，`docs/ARCHITECTURE_DECISIONS.md` AD-13 已经指出"这个决定在开发期间没有被正式确认过"，如果未来要迁移，需要真实的数据库设计能力 | 视情况——如果这个项目不会真的扩展到需要数据库，优先级可以放低 | 不需要在本项目里练，用一个明确需要关系查询的新项目练手更合适 |

---

**说明**：以上分类严格依据"本次整理能在代码/测试/脚本/文档中找到的证据"得出，不包含任何基于聊天历史印象的主观推测。如果读者（开发者本人）认为某项评级与自己的真实理解程度不符，应以自己的真实情况为准——这份文档的价值在于"给出可验证的证据清单"，而不是给出一个绝对准确的能力评分。
