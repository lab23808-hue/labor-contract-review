# 劳动合同智能审查系统

> 输入一份劳动合同文本 → 解析切分 → 检索法律依据 → 大模型逐条审查 → 规则补充 → 合并 → 审查报告 → 人工修改 / V2 / Diff

面向律所与法务场景的劳动合同审查工具。系统把「读合同、找法条、判风险、给修改建议」这条人工流程做成可交互的自动化链路，并保留人工确认环节。

> 系统输出仅供参考，不构成法律意见。

---

## 项目定位

一份劳动合同人工逐条比对劳动法往往需要数十分钟，且容易漏项。本项目解决三个问题：

1. **找法条**：为每条合同条款检索相关法律依据，审查结论必须能追溯到条文原文。
2. **判风险**：大模型负责开放性判断，确定性规则负责有明确法律标准的判断（如试用期时长、工资比例）。
3. **可复现**：审查报告固化模型、提示词、规则集、知识库四个版本号，同样的输入得到同样的结果。

---

## 核心能力

| 能力 | 说明 |
|---|---|
| 审查主链路 | 解析 → 按条切分 → 逐条检索 → LLM 审查 → 规则补充 → 合并 → 报告 |
| LangGraph 编排 | 6 节点工作流，检索与规则检查双路并行，合并节点汇合 |
| 可插拔检索 | BM25（关键词）/ Dense（BGE-M3 + Chroma）/ Hybrid（RRF 融合），按配置切换 |
| 规则兜底 | 试用期时长、试用期工资比例等确定性判断不依赖模型 |
| 证据可溯源 | 每条风险结论绑定检索到的法条 Evidence |
| 人机协同修改 | 「批次—任务—候选修改—校验—确认/拒绝」状态机，带重试上限 |
| 版本与对比 | 确认后重建 V2 全文，产出条款级 Diff 与风险级 Diff |
| 审查工作台 | React + Vite 前端：合同库、条款列表、报告、版本面板、Diff 视图 |

---

## 技术栈

- **语言与框架**：Python 3.13、FastAPI、Pydantic v2
- **编排**：LangGraph
- **检索**：BGE-M3（dense embedding）、Chroma（持久化向量索引）、BM25Okapi（char-bigram）
- **模型**：DeepSeek（OpenAI 兼容接口）
- **前端**：React + Vite
- **测试**：pytest

---

## 架构

```
src/
├── api/          HTTP 入口、依赖注入、路由、异常映射
├── app/          用例层：审查、V2 生成、Diff
├── config/       路径、模型、chunk、top-k 等默认配置
├── core/         跨层契约：Clause / Evidence / ReviewResult / Report / Protocol
├── domain/       业务域
│   ├── agents/      审查 Agent、修改 Agent、风险分析
│   ├── document/    解析、切分、V2 重建
│   ├── rules/       确定性规则
│   ├── diff/        条款级与风险级 Diff
│   ├── modification/修改任务状态机、校验、风险化解
│   └── prompts/     Prompt 模板
├── evaluation/   离线评估逻辑（不参与在线链路）
├── infra/        基础设施适配：合同存储、LLM 客户端
├── retrieval/    检索能力：Embedding、知识库加载、检索器、三种后端
└── workflow/     LangGraph 审查编排
```

依赖方向单向收敛：

```
api → app → workflow / domain → retrieval / infra → core
```

约束：

- `core` 不依赖任何具体实现
- `domain` 不依赖 HTTP
- `retrieval` 不依赖业务 Agent
- 路由不直接 import `domain` / `infra`，统一经由应用服务

---

## 审查数据流

```
合同文件（.txt）
  → DocumentParser 解析
  → ClauseSplitter 按条切分
  → LangGraph contract_loading
  → 分两路并行：
       ├─ retrieve → ClauseReviewer（生成 query → 检索 → Prompt → LLM → ReviewResult）
       └─ rule_check（确定性规则）
  → merge（合并去重）
  → report_assembly
  → ReviewReport
  → 人工确认修改 → V2 重建 → 条款级 / 风险级 Diff
```

---

## 关键设计

### 1. 双路并行 + 单条失败隔离

检索与 LLM 审查是一条链，规则检查从加载节点分出去并行，两条在合并节点汇合。单条条款审查失败只记入 `failed_clauses`，不中断整份报告——失败可见，但不会静默变成「无风险」。

### 2. 检索 query 的构造方式

从条款生成检索 query 时，只去掉「第X条」编号和「1.」「（一）」这类列表前缀，**保留标题**。

原因来自一次真实踩坑：条款标题往往是最精准的法律术语（如「竞业限制」），而正文常是同义改写、偏口语（如「不得到有竞争关系的单位任职」）。早期版本把标题整行删掉后，竞业限制相关法条直接检索不到。

### 3. 可插拔检索后端

检索层定义 `SimilaritySearchBackend` / `VectorSink` 两个 Protocol：

- `lexical` —— BM25 + char-bigram 分词
- `dense` —— BGE-M3 向量 + Chroma 持久化索引
- `hybrid` —— 两路召回后 RRF 融合

上层只依赖接口，换后端不改业务代码。默认策略为 BM25，无需构建索引即可运行。

### 4. 结构化输出 + 规则兜底

LLM 输出先用 Pydantic schema 校验，非法 JSON 直接抛错，不静默降级；再由规则层补齐试用期时长、试用期工资比例等确定性判断，两者按风险类型合并去重。

### 5. 修改闭环与版本对比

修改任务状态机：`pending → waiting_confirmation / needs_human → confirmed / rejected / abandoned`，带重试次数上限。确认后重建 V2 全文，并输出两层 Diff：条款级（新增/删除/修改）与风险级（新增/已消除/仍存在）。

---

## 评估结果

离线评估见 [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md)。

**50 份合成合同，BM25 检索**

| 指标 | 值 |
|---|---:|
| Recall@5 | 0.9603 |
| MRR@5 | 0.7479 |
| 规则 precision | 1.0 |
| 规则 recall | 0.8824 |

**同批 10 份合同的检索策略对比**

| 策略 | Recall@5 | MRR@5 |
|---|---:|---:|
| BM25 | 0.8667 | 0.6650 |
| Dense（BGE-M3） | 1.0000 | 0.6343 |
| Hybrid（RRF） | 1.0000 | 0.6994 |

> 说明：评估使用 Fake LLM，因此 LLM 风险一致率不代表真实模型质量；上述检索与规则指标不依赖 LLM。

---

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 2. 配置密钥（在项目根目录创建 .env）
#    DEEPSEEK_API_KEY=你的key
#    DEEPSEEK_MODEL=deepseek-chat

# 3. 校验知识库结构（不需要模型）
python scripts/validate_knowledge_base.py

# 4. 可选：构建 dense 索引（需要 BGE-M3，首次会下载模型）
python scripts/build_knowledge_base.py

# 5. 启动 API
uvicorn --app-dir src api.app:app --reload

# 6. 可选：启动前端
cd frontend && npm install && npm run dev
```

默认检索策略是 **BM25**，不需要 Chroma / BGE-M3。要用 Dense 或 Hybrid，把 `src/config/settings.py` 的 `RETRIEVAL_STRATEGY` 改为 `dense` / `hybrid`，并确保索引已构建。

---

## 测试

```bash
pytest
```

当前：**386 passed**，约 20 秒。

---

## 已知边界

- **只支持 `.txt` 解析**：PDF / DOCX / OCR 的解析器为占位实现，调用会抛 `NotImplementedError`。
- **知识库仅收录《中华人民共和国劳动合同法》**，构建后 32 条依据；来源与核验状态见 [data/knowledge/SOURCES.md](data/knowledge/SOURCES.md)。
- **Dense / Hybrid 需要先构建 Chroma 索引**，且索引是派生数据，不进版本库。
- **评估使用 Fake LLM**，LLM 质量指标未在真实模型上验证。
- **无鉴权、无 Docker、无多进程设计**，定位为单机原型。
- 修改 / 版本 / Diff 的服务层已有测试，但对应的 HTTP 路由缺少端到端用例。

---

## 文档

- [docs/architecture.md](docs/architecture.md) —— 架构说明
- [docs/adr](docs/adr) —— 架构决策记录
- [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md) —— 离线评估结果
- [REFACTOR_REPORT.md](REFACTOR_REPORT.md) —— 一次完整重构的任务清单与验收记录
