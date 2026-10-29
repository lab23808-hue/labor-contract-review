# 架构说明

## 分层

```text
api      → HTTP / DTO / Depends
app      → 用例服务（Review / V2 / Diff / Contract）
workflow → LangGraph 审查图
domain   → agents / document / rules / diff / modification / prompts
retrieval→ embedding / BM25 / Chroma / fusion
infra    → ContractManager / LLM client
core     → Pydantic 契约与 Protocol
config   → 常量与环境变量
evaluation → 离线评估
```

依赖方向：

```text
api → app → workflow/domain → retrieval/infra → core
```

- `domain` 通过 `domain/ports.py` 的 `LLMPort`、`StoragePort` 访问外部能力。
- `retrieval` 不依赖 domain/app/api。
- `infra` 实现端口，不承载业务规则。
- `api/routes` 不再直接 import `domain`/`infra`。

## 合同入库链路

```text
POST /contracts
  → 临时文件
  → ContractManager.create_contract
  → original_file/ + metadata.json (uploaded)

POST /contracts/{id}/parse
  → document.preparation.parse_and_split_contract
      → DocumentParser (txt; PDF/DOCX/OCR 未实现)
      → ClauseSplitter
  → parsed_text.txt + clauses.json (parsed/split)
```

合同**不进入向量库**。

## 知识库入库链路

```text
data/knowledge/*.txt
  → KnowledgeLoader.split_text
  → list[Evidence]
  → DenseBackend.embed_documents (BGE-M3)
  → ChromaColorStore.upsert
  → data/index/chroma (persistent)

同一批 Evidence 也可构建 BM25Index（进程内存）
```

## 检索审查链路

```text
POST /contracts/{id}/review
  → ReviewApplicationService
  → LangGraph:
       contract_loading
         ├→ retrieve → llm_review
         └→ rule_check
       merge
       report_assembly
  → ReviewReport
  → ContractManager.save_review

retrieve:
  clause → generate_query → LegalKnowledgeRetriever
         → BM25 / Dense / Hybrid(RRF)
         → retrieval_results[clause_id]

llm_review:
  clause + retrieval_results[clause_id] → Prompt → LLM → ReviewResult(evidences)

report_assembly:
  ReviewReport + ReviewVersions(llm_model/prompt/ruleset/knowledge base)
```

## 数据布局

```text
data/knowledge/          原始法条（版本可控）
data/index/chroma/       Chroma 持久化索引（可重建）
data/runtime/contracts/  用户合同与审查记录（运行数据）
data/eval_samples/       评估合同（由脚本生成）
data/eval_results/       评估结果（由脚本生成）
```
