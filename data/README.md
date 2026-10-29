# data/ 数据布局

`data/` 与 `src/` 平级，代码不放进数据目录，数据不放进源码目录。

```text
data/
├── knowledge/              # 原始知识库（可提交、可版本控制）
│   ├── 劳动合同法.txt
│   ├── SOURCES.md
│   └── VERSION
├── index/                  # 派生索引（gitignore，可重建）
│   └── chroma/
│       ├── chroma.sqlite3
│       └── <segment-uuid>/*.bin
└── runtime/                # 运行时数据（gitignore）
    └── contracts/
        └── <contract_id>/
            ├── original_file/
            ├── parsed_text.txt
            ├── clauses.json
            ├── metadata.json
            ├── review/
            ├── modification_tasks/
            ├── modification_batches/
            └── versions/
```

## 三类数据

| 目录 | 性质 | 是否进 Git | 是否可重建 |
|---|---|---|---|
| `knowledge/` | 原始法条、来源说明、知识库版本 | 是 | 否，是事实来源 |
| `index/chroma/` | Chroma 持久化索引 | 否 | 是，从 `knowledge/` 重建 |
| `runtime/contracts/` | 用户合同、解析结果、审查记录 | 否 | 否，需要备份 |

## VectorStore 存什么

`ChromaVectorStore` 写入 Chroma 的内容：

- `ids`：由 `KnowledgeLoader._evidence_id()` 生成的确定性 id
- `documents`：切分后的法条 chunk 文本
- `embeddings`：BGE-M3 dense 向量
- `metadatas`：`source`、`article`、`part` 等

Chroma 自己维护：

- `chroma.sqlite3`：collection、segment、记录元数据
- `<segment-uuid>/data_level0.bin`、`header.bin`、`length.bin`、`link_lists.bin`：HNSW 索引段

因此：

- **法条原文只以 `data/knowledge/` 为准**；向量库是派生索引。
- **不要单独移动或编辑 Chroma segment**；迁移时整个 `data/index/chroma/` 一起移动。
- 知识库文本变化后，重新运行 `scripts/build_knowledge_base.py`。
- 换成本地文件型向量库以外的服务（PGVector/Milvus）时，替换 `infra` 适配器与 `data/index` 配置即可，上层业务不需要改。

## 重建

```bash
python scripts/build_knowledge_base.py
python scripts/validate_knowledge_base.py
```

`data/runtime/contracts/` 不建议重建，应单独做备份。
