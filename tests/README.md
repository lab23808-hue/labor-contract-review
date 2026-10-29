# tests/ 说明

只保留覆盖当前主链路的测试；历史评测/快照类测试已移除。

## 运行

```bash
pytest
pytest -m unit
pytest -m "unit or module"
pytest -m graph
```

`pytest.ini` 已设置 `pythonpath = src`，不需要额外设置 `PYTHONPATH`。

## 分层

| 层 | 覆盖内容 |
|---|---|
| `unit` | schemas、切分、解析、合同存储、配置、LLM 客户端、Prompt、Reviewer、规则、Risk Diff、知识库校验 |
| `module` | 解析/切分集成、RAG store/loader/retrieval、BM25、API 依赖与路由 |
| `graph` | 真实 LangGraph 审查流程、API 全链路（LLM/检索用假对象） |

当前自动化测试数量约 **365**（以 `pytest` 实际收集为准）。

## 不在这里的验证

真实 BGE-M3 / Chroma / DeepSeek 的端到端验证在：

```bash
python scripts/verify_full_pipeline.py
python scripts/verify_rag_pipeline.py
python scripts/verify_real_retrieval.py
```

这些脚本会调用真实模型，可能产生 token 消耗。
