# 劳动合同智能审查系统

输入一份劳动合同文本 → 解析切分 → 检索法律依据 → LLM 逐条审查 → 规则补充 → 合并 → 审查报告 → 人工修改 / V2 / Diff。

当前只保留**合同审查主链路**。QA、日志平台、Docker、GraphRAG、多模态检索暂不实现。

> 系统输出仅供参考，不构成法律意见。

## 1. 技术栈

- Python 3.13 + Pydantic v2
- FastAPI
- LangGraph（审查工作流）
- LangChain 子包（Document / TextSplitter / Embeddings）
- BGE-M3（dense embedding）
- Chroma（持久化向量索引）
- BM25Okapi（char_bigram，默认检索策略）
- DeepSeek（OpenAI 兼容接口）
- React + Vite（前端）

## 2. 目录结构

```text
labor_contract_review/
├── src/
│   ├── api/                 # FastAPI 入口、依赖注入、HTTP 路由
│   ├── app/                 # 用例层：Review / V2 / Diff
│   ├── config/              # 全局配置常量
│   ├── core/                # 跨层契约：Clause / Evidence / ReviewResult / Report / Protocol
│   ├── domain/              # 业务域
│   │   ├── agents/          # 审查 Agent、修改 Agent、风险分析
│   │   ├── document/        # 解析、切分、V2 重建
│   │   ├── rules/           # 确定性规则
│   │   ├── diff/            # 条款/风险 Diff
│   │   ├── modification/    # 修改任务状态机、校验、风险化解
│   │   └── prompts/         # Prompt 模板
│   ├── evaluation/          # 离线评估逻辑（不参与在线链路）
│   ├── infra/               # 基础设施适配
│   │   ├── storage/         # 合同文件存储（ContractManager）
│   │   └── llm/             # LLM 客户端
│   ├── retrieval/           # 检索能力
│   │   ├── base.py          # SimilaritySearchBackend / VectorSink Protocol
│   │   ├── embedding.py     # BGE-M3 EmbeddingService
│   │   ├── knowledge_loader.py
│   │   ├── retriever.py     # Document → Evidence
│   │   └── backends/
│   │       ├── dense/       # 纯 Chroma store + DenseBackend
│   │       └── lexical/     # BM25Index + BM25Backend
│   ├── workflow/            # LangGraph 审查编排
│   └── main.py              # ASGI 入口
├── data/
│   ├── knowledge/           # 原始法律知识库（版本可控）
│   ├── index/chroma/        # Chroma 持久化索引（派生数据，gitignore）
│   └── runtime/contracts/   # 用户合同运行时数据（gitignore）
├── frontend/
├── scripts/                 # 离线建库、校验、真实验证脚本
├── tests/                   # pytest
├── pyproject.toml
├── pytest.ini
├── requirements.txt
└── README.md
```

## 3. 分层职责

| 目录 | 职责 | 不应该做什么 |
|---|---|---|
| `api/` | HTTP 请求解析、依赖注入、异常映射 | 业务规则、检索实现、文件存储细节 |
| `app/` | 用例编排：审查、V2、Diff | HTTP、Prompt 细节、Chroma 细节 |
| `core/` | 数据契约、跨层 Protocol、通用模型 | 外部 IO、具体后端实现 |
| `domain/` | 业务规则、条款处理、Agent、Diff、修改状态机 | HTTP、向量库连接 |
| `retrieval/` | 文本→向量、向量存储、检索后端、Evidence 转换 | 合同业务规则、HTTP |
| `workflow/` | LangGraph 节点、边、State | 检索实现、LLM 连接细节 |
| `infra/` | 合同存储、LLM 客户端等外部适配 | 业务流程 |
| `evaluation/` | 离线评估逻辑 | 在线请求链路 |
| `config/` | 路径、模型、chunk、top-k 等默认值 | 密钥、运行逻辑 |

依赖方向：`api → app → workflow/domain → retrieval/infra → core`。  
`core` 不依赖任何具体实现；`domain` 不依赖 HTTP；`retrieval` 不依赖业务 Agent。

## 4. 数据与 VectorStore

三类数据严格分开：

```text
data/knowledge/        原始法条文本：版本可控，是唯一事实来源
data/index/chroma/     Chroma 索引：由 knowledge 构建，可随时重建，gitignore
data/runtime/contracts/ 用户合同与审查记录：运行数据，gitignore
```

`VectorStore` 存的是：

- `ids`：Evidence 的确定性 id
- `documents`：chunk 文本
- `embeddings`：BGE-M3 向量
- `metadatas`：source / article / part 等
- Chroma 内部：`chroma.sqlite3` + HNSW segment（UUID 目录下的 `.bin`）

Chroma segment 是 Chroma 内部结构，不要单独移动或编辑；迁移整个 `data/index/chroma/` 即可。  
原始法条不在向量库里，向量库只是可重建的索引。

## 5. 运行

```bash
# 安装依赖
pip install -r requirements.txt

# 构建/重建 dense 索引（需要 BGE-M3，首次会下载模型）
python scripts/build_knowledge_base.py

# 校验知识库结构（不需要模型）
python scripts/validate_knowledge_base.py

# 启动 API
uvicorn --app-dir src api.app:app --reload

# 跑测试
pytest
```

默认检索策略是 **BM25**，不需要 Chroma / BGE-M3。  
要使用 Dense 检索，把 `src/config/settings.py` 的 `RETRIEVAL_STRATEGY` 改为 `"dense"`，并确保 `data/index/chroma/` 已构建。

## 6. 审查数据流

```text
合同文件
  → ContractManager 保存原件
  → DocumentParser 解析
  → ClauseSplitter 切分
  → LangGraph contract_loading
  → ClauseReviewer（每条 Clause）
      → generate_query
      → LegalKnowledgeRetriever
          → BM25Backend 或 DenseBackend
      → Prompt + DeepSeek
      → ReviewResult
  → RuleChecker
  → merge_review_results
  → ReviewReport
  → ContractManager.save_review
```

## 7. 配置

配置集中在 `src/config/settings.py`；密钥只从 `.env` / 环境变量读取：

- `RETRIEVAL_STRATEGY`：`bm25` / `dense`
- `RETRIEVAL_TOP_K`
- `EMBEDDING_MODEL_NAME`
- `CHROMA_COLLECTION_NAME`
- `CLAUSE_CHUNK_SIZE` / `CLAUSE_CHUNK_OVERLAP`
- `KNOWLEDGE_CHUNK_SIZE` / `KNOWLEDGE_CHUNK_OVERLAP`
- `LLM_MODEL_NAME`
- `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL`（`.env`）

## 8. 已知边界

- 只解析 `.txt`；PDF / DOCX / OCR 仍是占位。
- 默认 BM25；Dense 需要额外构建索引。
- `ReviewVersions` 版本字段目前未填充。
- 检索结果暂不保存 Evidence 引用，证据链仍可继续增强。
- 无 QA、无 Docker、无 Langfuse/Redis。
