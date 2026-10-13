# 项目知识树

> **2026-09-29 更新说明**：本次知识库整理在原有知识树基础上补充 Modification Agent / LangGraph 未完善项 / HITL / V1-V2 / Diff / FastAPI / React / 历史设计 / PITFALLS / 技术债务 / 面试能力等节点，并按"知识树整理指南"第九节的完整节点清单重新组织为下面的【当前版本】。**不删除原有内容**：2026-09-28 的原始版本完整保留在本文件末尾的【历史版本（2026-09-28）】一节。
>
> 评级图例：已掌握 / 已接触但理解不足 / 尚未掌握 / 证据不足，暂不评级——**只有能对应到真实写过的代码、真实修复过的 bug、真实跑过的验证时才标注前三档，没有这类证据一律标"证据不足，暂不评级"，不臆测能力**。
> 原图例继续沿用：✅ 已在真实环境验证　🧪 仅自动化测试覆盖　⚠️ 有已知限制　📝 项目未实现 / 未使用

## 【当前版本】完整知识树（2026-09-29）

```
劳动合同智能审查系统
│
├── 业务（做什么、为谁做）                                    已掌握
│   ├── 目标：律师/合规人员上传劳动合同 → 自动发现风险条款 → 给出法律依据与建议
│   ├── 当前实际做到：单份 .txt 合同的全链路 V1 审查 + 律师发起条款修改
│   │   （Modification Agent + HITL）+ 生成 V2 + V1/V2 Diff 与风险 Diff
│   └── 未做到：批量合同、PDF/DOCX、多用户权限、法律知识库规模化
│
├── 系统架构                                                  已掌握
│   ├── React 前端 → FastAPI → Contract/Parser/Clause → Review Pipeline
│   │   （LangGraph）→ LLM + RAG + RuleChecker → ReviewReport
│   └── Modification Agent → V1 → V2（重新解析/切分/审查）→ Diff
│
├── Contract（ContractManager，文件系统存储）                 已掌握
│   ├── contract_id = uuid4 hex + 正则校验（防路径穿越）
│   ├── original_file 只写一次；metadata.json 最后原子写入
│   ├── review/ 目录按 contract_version 隔离历史审查记录（不可覆盖）
│   ├── modification_tasks/、versions/ 子目录（V2 相关持久化）
│   └── ⚠️ 早期设想 SQLite，最终是纯文件系统 JSON（P-见 DEVLOG）
│
├── Parser（DocumentParser）                                  已掌握　📝 仅 .txt
│   └── 解析不改动原文，保证 Clause 偏移量不变量成立
│
├── Clause（ClauseSplitter）                                  已掌握
│   ├── 正则结构切分（条→款）+ 超长条款二次切分
│   ├── hierarchy_level=0（条）/ 1（款，parent_clause 指回条）
│   └── 不变量：full_text[start_char:end_char] == original_text
│       （P-22 的根因正是对这棵树"父节点是否包含子节点内容"的隐含假设出错）
│
├── Review（LLM Review + RuleChecker + Merge）                已掌握
│   ├── LLM Review：ClauseReviewer，逐条 query→RAG→Prompt→LLM→ReviewResult
│   ├── RuleChecker：测试驱动的漏检补丁层，独立于 LLM 结果运行
│   ├── merge：纯拼接，不覆盖不去重
│   └── 为什么不是单纯规则系统/单纯 RAG：见 PROJECT_KNOWLEDGE 第八节
│
├── RAG                                                       已掌握
│   ├── 法律文本按"第X条"切分，一条一个 Evidence
│   ├── BGE-M3 稠密向量（归一化）+ Chroma 持久化
│   ├── 定位：证据层，不决定"审查哪些条款"
│   └── ⚠️ 知识库仅 14 条节选；无相关性阈值
│
├── LangChain                                                 已接触但理解不足
│   ├── 用到：HuggingFaceEmbeddings、RecursiveCharacterTextSplitter、
│   │   langchain_core.embeddings.Embeddings 接口
│   └── 没有证据表明系统性使用过 LangChain 的 Chain/Agent 抽象
│       （本项目的"Agent"是自己手写的 Function Calling 编排，不是
│       LangChain AgentExecutor）
│
├── LangGraph（review/pipeline.py）                            已掌握，但只用到很小一部分能力
│   ├── State：6 字段，单一写入者；Node：5 个；Edge：7 条，全无条件边
│   ├── 并行（contract_loading 扇出）+ 汇合（两条边汇入 merge）
│   ├── 异常传播：节点异常直接终止整图（已知架构决策，非缺陷）
│   └── 未用到：conditional edges、reducer、retry、checkpoint、streaming   📝
│
├── Agent（本项目对"Agent"的界定）                            已掌握
│   ├── LLM Review：不是 Agent，是"LLM 增强的 workflow 里的一个判断节点"
│   ├── Modification Agent：**带校验和人工确认的单次工具调用 Agent**——
│   │   由 LLM 通过真实 Function Calling 决定"要不要调用、怎么填参数"，
│   │   但工具集固定为一个（modify_clause），不做多工具自主选择，
│   │   不做多步规划，每次任务只调用一次 Agent、产出一个候选，
│   │   决策权（confirm/reject）永远在人（律师）手中
│   └── 不是"完全自主的复杂 Agent"（无多工具选择、无自主终止条件、
│       无多步规划循环）
│
├── Function Calling                                          已掌握
│   ├── modify_clause 工具（JSON Schema），tool_choice="auto"（P-21）
│   ├── 真实 DeepSeek 调用返回结构化 tool_calls，非文本正则抠 JSON
│   └── 第一道防线（tool.py 校验 clause_id）+ 第二道防线（validator.py
│       范围/完整性/结构校验）
│
├── HITL（Human-in-the-loop）                                 已掌握
│   ├── 状态机：pending→reviewing→confirmed→completed；
│   │   reject→rejected→（重试<3）pending；attempts_exhausted→needs_human
│   ├── 确认/拒绝永远由外部（律师，通过 API）触发，无自动确认
│   └── 每轮重试永远基于 V1 原文 + 全部历史意见重新生成，不基于上一轮候选
│
├── Modification（modification/）                             已掌握
│   ├── agent.py（Agent）/ tool.py（工具执行）/ validator.py（纯函数校验）/
│   │   prompts.py（Prompt+Schema）/ service.py（编排层）
│   └── ⚠️ 技术债务：没有 tests/test_modification*.py 自动化 pytest 覆盖，
│       只有 scripts/verify_modification.py 等手工验证脚本（证据：
│       tests/ 目录下没有对应文件，见 KNOWLEDGE_GAPS）
│
├── V1/V2                                                     已掌握
│   ├── V1：合同上传后的原始 contract_id；永不被覆盖
│   ├── V2：内部另一个 contract_id（ContractVersion 映射），经过完整
│   │   解析+切分+独立复审，不是"打补丁"
│   └── ⚠️ 已发现并修复过 3 个真实 bug（P-22/23/24，见 PITFALLS）
│
├── Diff（Clause Diff / Risk Diff）                            已掌握
│   ├── Clause Diff：按 clause_id 对比 hierarchy_level==0 的 original_text，
│   │   matched=False 时不猜测对应关系
│   ├── Risk Diff：按 (source, clause_id/rule_id) 做 key 匹配，
│   │   五类 category：resolved/unchanged/changed/new/unmatched
│   └── 为什么不用 related_clause_ids 匹配：见 ARCHITECTURE_DECISIONS
│
├── FastAPI（api/）                                            已掌握
│   ├── app.py + dependencies.py（lifespan/AppState/Depends）+
│   │   routes/contracts.py + routes/modification.py
│   ├── 依赖注入：ModificationService 现场组装而非启动时单例（P-20 修复）
│   └── ⚠️ README.md、docs/INTERVIEW.md、docs/KNOWLEDGE_TREE.md（本文件
│       历史版本）都曾记录"api/、output/ 是空包"——这是**文档与代码不一致**，
│       api/ 现已完整实现，output/ 仍是空包（见下方"文档与代码不一致"）
│
├── React（frontend/）                                         已接触但理解不足
│   ├── App.jsx 持有全部顶层状态，唯一调用后端 API 的地方；
│   │   子组件（ContractLibrary/ContractWorkspace/…）只通过 props/回调交互
│   ├── api/client.js 是唯一的 fetch 封装层
│   └── 没有路由、没有状态持久化（localStorage）——刷新后回到未选中合同
│
├── 工程实践                                                  已掌握
│   ├── 配置集中（config/settings.py）、测试分层（unit/module/graph）
│   ├── 依赖注入生命周期管理（P-20：单例 vs 现场组装）
│   └── Mock 与真实依赖的边界（P-01）
│
├── 测试                                                      已掌握
│   ├── pytest 自动化测试：298 个测试函数（tests/*.py 统计，2026-09-29
│   │   本次整理用 grep 实测得出，含 test_api_contracts.py 34、
│   │   test_schemas.py 39 等；历史 DEVLOG 记录的 258 是更早阶段的数字，
│   │   两者不矛盾——API/Modification/DI 相关测试是后续新增的）
│   ├── scripts/ 下的手工真实验证脚本（verify_*.py），覆盖 RAG/规则/
│   │   pipeline/DI/Function Calling/V2 重建/换行修复等，共 13 个
│   └── ⚠️ Modification Agent 业务逻辑没有对应的 tests/test_modification*.py
│
├── 历史设计（已被推翻但保留记录）                            已掌握
│   ├── rules/ 的 ContractFacts 统一事实层（P-06，已删除）
│   ├── review 合并策略：曾设想"规则替换 LLM"，改为纯拼接（P-06/P-07）
│   ├── ModificationService 曾作为启动时单例存进 AppState（P-20，已改为
│   │   现场组装）
│   └── _build_v2_text 曾只拼接 hierarchy_level==0（P-22，已修复）
│
├── PITFALLS（见 docs/PITFALLS.md）                            已掌握
│   ├── P-01~P-21：8 字段格式，覆盖沙箱/RAG/LLM/规则/测试/工程/DI/
│   │   Function Calling 等 21 个真实问题
│   └── P-22~P-24：12 字段格式，覆盖 V2 重建丢款、review_id 撞车、
│       换行符损坏（均已在真实环境验证修复）
│
├── 技术债务                                                  已掌握（见 PROJECT_KNOWLEDGE 第八节）
│   ├── Modification 模块缺少自动化 pytest 覆盖
│   ├── legal_basis 没有程序化校验（只有 Prompt 约束）
│   ├── clause_diff 的"条与条之间固定 \n\n 分隔"未做与 V1 逐字节对齐的规范化
│   └── ReviewReport 不进 LangGraph State；文档字符串漂移（SQLite/重试等）
│
├── 待完善业务逻辑                                            证据不足，暂不评级（只列已知真实缺口）
│   ├── 跨条款分析仅限规则手工覆盖的两条（试用期工资/期限），无通用机制
│   ├── 知识库覆盖仅 14 条节选，规则仅 2 条
│   ├── unknown/needs_review 类状态未系统化（目前靠"依据不足"文字说明）
│   └── 修改任务之间没有依赖图（多任务冲突只做最简单的同条款检测）
│
├── LangGraph 待完善                                          已掌握（能说清"为什么现在不做"）
│   ├── Conditional Routing / Retry / Error Recovery（P-14 已知取舍）
│   ├── Tool Selection Agent（当前 Modification Agent 只有一个工具，
│   │   未来若工具增多，可在 modification/agent.py 与 service.py 之间
│   │   加一层选择/路由，不需要动 LangGraph review 主图）
│   └── Cross-Clause Analysis、更复杂 HITL（多轮协商、任务依赖图）
│
└── 面试能力                                                  已掌握（见 docs/INTERVIEW_QA.md）
    ├── 项目级/架构级/Agent/LangGraph/工程/Bug-Debug/设计题
    └── 必考题：为什么 V2 中未修改条款出现额外空行？（P-24 全流程）
```

### 文档与代码不一致（本次整理新发现，需要重点标注）

| 文档 | 记录的内容 | 与当前代码的差异 |
|---|---|---|
| `README.md` 第 134/429/459 行 | "`api/`、`output/` 为空包，尚未实现" | `api/` 已完整实现（`app.py`/`dependencies.py`/`routes/contracts.py`/`routes/modification.py`，含完整的合同、审查、修改任务、V2、Diff 路由）；`output/` 目前确认仍是空包（`output/__init__.py` 内容为空，本次整理已核实）。**本次整理不修改 README.md（属于硬约束禁止修改的文件），此处仅记录不一致，供后续开发者手动更新 README。** |
| `docs/INTERVIEW.md`（旧文件，见下方历史存档）A2、"不要说的话" | "有 API / 前端"→"api/、output/ 是空包" | 同上，已在 `docs/INTERVIEW_QA.md` 新文件中更正，旧文件本身按"保留历史"原则不删除，只加了重定向说明 |
| `docs/KNOWLEDGE_TREE.md`（本文件历史版本，见下） | "尚未实现：HTTP API（api/）、结果格式化（output/）" | 同上，已在本文件【当前版本】里更正；历史版本原样保留在下方，注明"该记录已过时" |
| `docs/DEVLOG.md`（旧文件） | 未覆盖 Modification/V1V2/Diff/API/前端 | 不是"错误"，是"尚未覆盖"——已在 `docs/DEVELOPMENT_LOG.md` 新文件中补齐 |
| `schemas/contract.py`、`schemas/_time.py` 文档字符串 | 提到 SQLite | 实际是纯文件系统 JSON（P-16/P-17，历史已知，本次复核代码确认仍然存在这个字符串漂移，未修改代码） |

---

## 【历史版本（2026-09-28）】

> 以下为本次整理之前的原始知识树，完整保留，仅供追溯。其中"尚未实现"一节里的 `api/`、`output/` 记录已经过时，请以上方【当前版本】为准。

```
劳动合同智能审查系统
│
├── 业务链路
│   ├── 合同登记与存储（ContractManager）              ✅
│   │   ├── contract_id = uuid4 十六进制 + 正则校验 → 防路径穿越
│   │   ├── 原文件只写一次（审计依据），metadata.json 最后原子写入
│   │   └── 状态：uploaded → parsed → split         ⚠️ 没有代码置为 reviewed / failed
│   │
│   ├── 文档解析（DocumentParser）                      ✅ .txt　📝 PDF / DOCX / OCR
│   │   └── 解析不改动原文 → 保证条款偏移量成立
│   │
│   ├── 条款切分（ClauseSplitter）                       ✅
│   │   ├── 阶段一：正则结构切分（第X条 → 款），建立 parent_clause
│   │   ├── 阶段二：只有超长条款才用 RecursiveCharacterTextSplitter
│   │   └── 不变量：full_text[start_char:end_char] == original_text
│   │
│   ├── RAG                                              ✅
│   │   ├── 法律文本按"第X条"切分，一条一个 Evidence
│   │   ├── BGE-M3 稠密向量（归一化），本地加载
│   │   ├── Chroma 持久化；embedding 由 Chroma 内部调用
│   │   └── 检索 → Evidence（distance 越小越相似）    ⚠️ 知识库只有 14 条
│   │
│   ├── LLM Review                                       ✅
│   │   ├── generate_query（只去编号，保留标题）
│   │   ├── Prompt 约束：只依据给定依据、依据不足要说明、只输出 JSON
│   │   ├── DeepSeek（OpenAI 兼容接口，JSON 模式）
│   │   ├── LLMReviewOutput 校验 → 代码补 clause_id / source
│   │   └── ReviewError（检索 / 调用 / 非法 JSON / 结构不合法）  ⚠️ 结果非确定性
│   │
│   ├── RuleChecker                                      ✅ 2 条规则
│   │   ├── probation_salary（百分比 < 80%）
│   │   ├── probation_duration（第十九条阶梯，跨条款）
│   │   └── 只返回发现的问题；不读 llm_results       ⚠️ 识别范围有限
│   │
│   ├── 结果合并（merge_review_results）                 ✅ 纯拼接
│   └── 结果结构（ReviewResult / ReviewReport）          ✅ 风险点粒度
│
├── LangGraph                                            ✅ 真实 LangGraph 1.2.12
│   ├── State：6 字段，每字段单一写入者
│   ├── Node：5 个，薄封装
│   ├── Edge：7 条，全是无条件边
│   ├── Parallel：contract_loading 扇出到 llm_review 与 rule_check
│   ├── Merge：两条边汇入 merge，框架等两个上游都完成
│   ├── Exception：节点异常原样向上抛出（graph 测试确认到 isinstance 级）
│   └── 未使用的能力：conditional edges、reducer、retry、checkpoint、streaming   📝
│
├── Agent 架构认知
│   ├── LLM   — 在 llm_review 节点内做概率性判断
│   ├── RAG   — 被 ClauseReviewer 直接调用的检索步骤（不是 LLM 自主选择的工具）
│   ├── Rule  — 确定性代码，补主线路结构上做不到的判断
│   ├── Workflow — 拓扑固定的流程（本项目）
│   └── Agent — 由 LLM 动态决定下一步（本项目不是）
│
├── 工程能力
│   ├── 配置管理 — config/settings.py，只放默认值，不放密钥           ✅
│   ├── 模块依赖 — schemas 为基础层；config 零依赖；pipeline 是唯一汇总点   ✅
│   ├── 测试体系（见第三节）
│   │   ├── Unit / Module / Graph                                   ✅
│   │   ├── E2E（scripts/）                                          ✅
│   │   ├── Mock / Fake                                              ✅
│   │   ├── 真实依赖验证                                             ✅
│   │   ├── 变异测试（手工 3 例）                                    🧪
│   │   └── pytest 基础设施：conftest.py / pytest.ini / markers      ✅
│   ├── 异常传播 — LLM 单条款失败进 failed_clauses，其余向上抛        ✅
│   └── 开发流程 — 先设计后编码；真实验证；文档化取舍与踩坑
│
└── 尚未实现
    ├── HTTP API（api/）、结果格式化（output/）                       📝
    ├── PDF / DOCX / OCR 解析                                         📝
    ├── 合同状态置为 reviewed / failed                                 📝
    ├── Evidence 随结果保存、ReviewVersions 数据来源                   📝
    └── 重试 / 超时 / 逐规则容错                                        📝
```

## 二、概念速查

### LangGraph

| 概念 | 是什么 | 在本项目里 |
|---|---|---|
| State | 图运行期间共享的、有类型的数据容器；节点之间不互相调用，只通过 State 交换数据 | `ReviewGraphState`，6 个字段 |
| Node | 读 State、返回"部分更新"的函数 | 5 个，每个只是对一个已验证业务函数的薄封装 |
| Edge | 决定执行顺序 | 7 条无条件边 |
| 并行分支 | 同一个节点引出多条边，下游节点在同一步执行 | `contract_loading → llm_review` 与 `→ rule_check` |
| 汇合（fan-in） | 一个节点有多条入边，框架等所有上游完成才执行它 | `llm_review → merge`、`rule_check → merge` |
| merge 的两层含义 | ① 图结构层的汇合（框架负责）；② 业务层 `merge_review_results`（我们的函数，纯拼接） | 两个不要混 |
| reducer | 声明"多个节点写同一个 key 时怎么合并" | 没用到：每个字段只有一个写入者 |
| 条件边 | 运行时才决定走哪条边 | 没用到：并行与汇合都用普通边 |
| 为什么是图而不是函数串联 | 拓扑声明式、可读可测；并行 / 汇合语义由框架保证；类型化 State；将来加条件边、重试、checkpoint 不用重写 | ⚠️ 当前只用到很小一部分能力，一个 fork/join 用函数加线程池也能实现 |

### Agent 架构

| 概念 | 含义 | 本项目 |
|---|---|---|
| LLM | 概率性的语言模型 | 判断单个条款，输出 JSON |
| RAG | 检索增强：先检索依据，再让 LLM 基于依据判断 | 检索是流程里写死的一步，不是 LLM 决定的 |
| Tool（Agent 语境） | LLM 可以自主选择调用的函数 | **没有**这种意义上的 tool |
| Rule | 确定性代码 | `RuleChecker` 的规则 |
| Workflow | 步骤与分支预先定义好 | 本项目的类型 |
| Agent | LLM 动态决定下一步做什么、何时结束 | 本项目**不是**；不要自称自主 Agent |

### RAG 与 LLM

- **embedding 与向量库**：文本 → 向量；检索是"找与 query 向量最近的向量"。本项目的 embedding 由 Chroma 在写入和检索时内部调用。
- **distance**：越小越相似；具体度量取决于 Chroma 配置，项目不做二次加工，所以**数值没有绝对含义、不同集合不可比**。
- **JSON 模式**：`response_format={"type": "json_object"}`，通常还需要 Prompt 里明确要求输出 JSON。
- **为什么不让模型填 `clause_id`、`source`**：这些是代码知道的事实，不该由概率模型生成。
- **`temperature=0` 不等于可复现**：同一输入两次真实调用，边界条款的风险等级出现过翻转。
- **`legal_basis` 是否真的来自检索**：目前靠 Prompt 约束与人工观察，**没有程序校验**。

### 数据与存储

- **风险点粒度**：`ReviewResult` 代表一个风险点，一个条款可有多条结果；因此 `summary` 统计的是结果数，不是条款数。
- **计算字段**：`summary`、`overall_risk_level` 由 `results` 推出，不存储，避免与明细不一致。
- **偏移量不变量**：`full_text[start:end] == original_text`；解析与存储层不得改动原文。

### 工程

| 概念 | 要点 |
|---|---|
| Mock 与 Fake | Mock（`unittest.mock.patch`）替换一个名字并可断言调用；Fake 是手写的、带简化真实行为的对象（如 `FakeEmbeddings`） |
| 替换的位置 | 替换**被测模块里引用的那个名字**（`patch("llm.client.OpenAI")`），不是去改某个库本身 |
| 异常传播 | 节点里抛出的异常会一路向上抛出，终止整图；本项目只在 `llm_review` 里按条款捕获 `ReviewError` |
| 变异测试 | 故意破坏生产逻辑，看测试会不会变红，检验测试的区分力 |
| marker 的使用与注册 | 使用只是创建标签（任意名字都行）；注册是在配置里声明它是合法的，警告用来防拼写错误 |
| `conftest.py` 与 `pytest.ini` | 前者放 pytest 钩子与共享逻辑（这里是自动分层）；后者放静态配置（路径与 marker 注册） |
| 配置集中的副作用 | 引用即依赖，依赖图会变；默认参数在函数定义时求值，改配置需重启 |

## 三、测试体系

```
测试体系
├── Unit Test        → 验证局部逻辑
├── Module Test      → 验证模块协作
├── Graph Test       → 验证 LangGraph 拓扑与状态流转
│   ├── LangGraph State
│   ├── Node
│   ├── Branch
│   ├── Merge
│   └── Exception Propagation
├── E2E Test         → 验证真实系统链路
└── pytest 基础设施
    ├── conftest.py
    ├── pytest.ini
    └── markers
```

| 层 | 验证什么 | 本项目里的例子 | 外部服务 |
|---|---|---|---|
| Unit | 局部逻辑 | 第十九条各档试用期上限的边界值（`test_rules_probation_duration.py`） | mock / 假对象 |
| Module | 模块协作 | 真实 Chroma 的写入与检索（`test_rag_database.py`） | embedding 用假向量 |
| Graph | 拓扑与状态流转 | 两个分支都执行、汇合不覆盖、`failed_clauses`、异常向上抛出（`test_review_pipeline.py`） | 只有 LLM 与检索是假的，**LangGraph 真实** |
| E2E | 真实系统链路 | `scripts/verify_full_pipeline.py` | **全部真实** |

**为什么四层缺一不可**

- **Graph 测试不能被 Unit 替代**：每个节点函数的单测都通过，也不能保证边接对了。如果有人漏掉 `rule_check → merge` 这条边，各函数单测照旧全绿，只有图级断言（`rule_results` 数量、`final_results = llm_results + rule_results`）会失败。这是按断言逻辑做的推断，没有实际删边验证过。
- **E2E 不能替代 Graph 测试**：E2E 慢、花钱、依赖网络，LLM 有非确定性，而且无法按需制造"LLM 单条失败""规则抛异常"这类路径；graph 测试不需要网络，几十秒就能跑完。
- **Mock 不能替代 E2E**：Mock 只验证"我以为它怎么工作"。本项目有三件事只有真实调用才暴露：DeepSeek 旧模型名已下线、`generate_query` 丢标题关键词导致召回失败、`HuggingFaceEmbeddings` 构造即加载模型。
- **E2E 不能替代 Unit**：E2E 失败时定位不到具体层，也很难覆盖边界值与失败路径。

**各层数量**：总数 258、graph 12（`12 passed, 246 deselected`）已在真实环境确认；unit 184 / module 62 是按 `tests/conftest.py` 的登记推算的，没有逐层单独核对。

## 四、验证状态汇总

| 类别 | 内容 |
|---|---|
| ✅ 真实环境验证过 | 258 个自动化测试；graph 12 个（真实 LangGraph 1.2.12）；真实检索；单条款审查；LLM + 规则 + 合并（10 条款）；完整 LangGraph E2E（5 → 5 + 2 → 7，0 失败）；整理后复跑 |
| 🧪 仅自动化测试 / 沙箱验证 | 各层测试的分层数量（推算）；11 项默认值整理前后等价；三个变异检查（在沙箱替身上做的） |
| ⚠️ 已知限制 | LLM 非确定性；单条款审查的跨条款盲区；知识库只有 14 条；规则只有 2 条；异常直接终止整图；`ReviewReport` 不进 State；`ReviewVersions` 为空；部分文档字符串漂移 |
| 📝 未实现 | API、结果格式化、PDF / DOCX / OCR、合同状态 `reviewed` / `failed`、`Evidence` 保存、重试 / 超时 |

**只验证到一次的项目**：完整 E2E 与 10 条款合同都是有限次数的真实运行；LLM 部分的具体风险等级分布不保证每次相同，规则部分（文字完全相同）和证据明确的 `high` 结论保持稳定。
