# scripts/ 索引

所有脚本从**项目根目录**运行，脚本内部会把 `src/` 加入 `sys.path`。

## 保留的脚本

| 脚本 | 用途 | 外部依赖 |
|---|---|---|
| `build_knowledge_base.py` | 离线构建/重建 Chroma 正式索引：切分 → BGE-M3 → upsert | 真实 BGE-M3、Chroma |
| `validate_knowledge_base.py` | 校验 `data/knowledge/*.txt` 的条号、空块、重复、超长条文 | 纯标准库 |
| `verify_full_pipeline.py` | 真实端到端：合同 → 解析 → 检索 → LLM → 规则 → 报告 | 真实 BGE-M3 + Chroma + DeepSeek，消耗 token |
| `verify_rag_pipeline.py` | 用临时 Chroma 验证“条款 → query → 检索 → Evidence” | 真实 BGE-M3 |
| `verify_real_retrieval.py` | 用正式 `data/index/chroma` 验证真实检索 | 真实 BGE-M3 |
| `verify_review_pipeline.py` | 单条款 LLM 审查（不经过 LangGraph） | 真实 DeepSeek |
| `verify_rules_pipeline.py` | RuleChecker + 合并验证 | 真实 DeepSeek（主线路） |
| `verify_modification.py` | 修改任务状态机、Validator、Risk Analyzer、V2 生成 | 真实文件系统；LLM 用假实现 |
| `_common.py` / `_samples.py` | 脚本共用环境加载与示例数据 | 无 |

## 常用命令

```bash
python scripts/build_knowledge_base.py       # 重建 dense 索引
python scripts/validate_knowledge_base.py    # 知识库结构检查
python scripts/verify_full_pipeline.py       # 真实端到端（会消耗 token）
```

`build_knowledge_base.py` 会写入 `data/index/chroma/`；该目录是派生数据，不进 Git。
