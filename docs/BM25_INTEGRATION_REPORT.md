# BM25 正式接入报告（2026-10-12）

## 0. 范围与前提

本轮只做"正式检索接入 + 必要的验收"，**没有**：
- 扩充正式知识库内容（`experiment_kb/working/` 的候选条文没有被导入 `data/knowledge/`）；
- 重构 RAG 以外的任何模块；
- 修改 `api/app.py`、`api/routes/*`、`agents/review_agent.py`、业务审查流程、生产 Chroma 索引（`data/chroma/`）、生产知识库文本（`data/knowledge/*.txt`）。

**一个必须明确的限制**：当前会话没有 `device_bash` 工具，无法在你的机器上执行命令
（无法跑 `pytest`、无法启动 `uvicorn`）；云端沙箱没有 `chromadb`/`langchain_chroma`/
`langchain_huggingface`/`fastapi` 等重依赖，也无法真正跑这个项目。所以下面"测试结果"
一节会严格区分"我在沙箱里实际做到了什么"和"你需要在本机验证什么"，不会把后者写成
已通过。

## 1. 改动文件清单

### 新建

| 文件 | 内容 |
|---|---|
| `rag/bm25_index.py` | `char_bigram_tokenizer()`、`BM25KnowledgeIndex` 类、`BM25IndexBuildError` 异常类。BM25Okapi（k1=1.5, b=0.75），纯标准库实现，算法与分词器照搬 `experiment_kb/scripts/eval_working_kb_retrieval.py::_BM25Index`/`_char_bigram_tokenizer()`（已用真实实验反复验证过的实现）。 |
| `tests/test_rag_bm25_index.py` | `BM25KnowledgeIndex` 的单元测试：分词器行为、空知识库/空白内容/重复条目报错、相似但不同内容不算重复、检索排序、k 校验、metadata/score_type 正确性、与 `LegalKnowledgeRetriever` 的集成。 |

### 修改

| 文件 | 改动内容 |
|---|---|
| `rag/retriever.py` | 新增 `SimilaritySearchBackend`（`typing.Protocol`，结构化类型）；`LegalKnowledgeRetriever.__init__` 的 `knowledge_base` 类型标注从 `ChromaKnowledgeBase` 放宽为这个 Protocol。**检索/转换逻辑本身零改动**（`search_legal_knowledge`/`_to_evidence` 逐字未动）。 |
| `rag/__init__.py` | 追加导出 `BM25KnowledgeIndex`、`BM25IndexBuildError`、`char_bigram_tokenizer`、`SCORE_TYPE`、`SimilaritySearchBackend`。 |
| `config/settings.py` | 新增常量 `RETRIEVAL_STRATEGY = "bm25"`（只能是 `"bm25"` 或 `"dense"`）。 |
| `api/dependencies.py` | `AppState.embedder`/`AppState.knowledge_base` 改为 `Optional`；`build_app_state()` 按 `settings.RETRIEVAL_STRATEGY` 分支构造检索后端（见下一节）；`get_embedder`/`get_knowledge_base` 返回类型同步改为 `Optional`。 |
| `tests/conftest.py` | `TEST_LAYERS["module"]` 里登记新测试文件 `test_rag_bm25_index.py`（本项目的测试分层机制强制要求，否则 pytest 收集阶段直接报错）。 |
| `tests/test_api_dependencies.py` | `_patch_heavy_builders()` 显式 `monkeypatch.setattr(settings, "RETRIEVAL_STRATEGY", "dense")`，让原有 3 个测试继续测 Dense/Chroma 路径本身，不随生产默认值变化改变含义；新增 3 个测试覆盖 BM25 路径（选择性初始化、空知识库报错、非法策略报错）。 |
| `tests/test_api_full_flow.py` | 同上，`_patch_heavy_builders()` 显式钉回 `"dense"`（这个文件测的是 review 全链路贯通，不是检索策略本身）。 |
| `tests/test_api_contracts.py` | 同上。 |

**没有改动** `rag/database.py`、`rag/knowledge_loader.py`、`rag/embedding.py`、
`agents/review_agent.py`、`api/app.py`、`api/routes/*`、`requirements.txt`
（BM25 算法纯标准库实现，确认不需要新依赖）。

## 2. 配置切换机制

`config/settings.py`：

```python
RETRIEVAL_STRATEGY = "bm25"   # 或 "dense"
```

`api/dependencies.py::build_app_state()` 在应用启动（`lifespan`）时读取这个值，二选一地
构造检索后端，两条分支互斥：

- `"bm25"`（默认）：**不**调用 `build_embedder()`、**不**初始化 `ChromaKnowledgeBase`
  （`AppState.embedder`/`AppState.knowledge_base` 都是 `None`）。只读取
  `settings.KNOWLEDGE_DIR`（即 `data/knowledge/*.txt`）下的正式知识库文本，复用
  `KnowledgeLoader.load_directory()` 的"读文件 → 按条切分"逻辑（与写入 Chroma 时完全
  同一套代码路径）构建 `BM25KnowledgeIndex`。构建失败（空目录、无效条文、重复条目）
  直接抛 `BM25IndexBuildError`，`build_app_state()` 不捕获，应用启动失败，不会降级到
  Dense。
- `"dense"`：逐字沿用原有流程——加载 BGE-M3、打开 Chroma、构造
  `LegalKnowledgeRetriever(knowledge_base=chroma_kb)`，和接入前完全一样。
- 非 `"bm25"`/`"dense"` 的任何其他取值：`build_app_state()` 直接抛 `ValueError`。

`agents/review_agent.py::ClauseReviewer`、`api/routes/*` 等所有调用方只认
`LegalKnowledgeRetriever.search_legal_knowledge(query, k)` 这一个接口，完全不感知、
也不需要感知背后是哪一种策略——这是本次接入要保持的模块边界。

## 3. 候选知识库与正式版本的差异

**本轮没有产生差异**，因为本轮没有做知识库扩容：

- BM25 直接读取生产 `data/knowledge/` 下现有的 `劳动合同法.txt`（当前只有这一个
  `.txt` 文件，10067 字节），与 Dense/Chroma 索引用的是**同一份源文件**，没有另建
  一套知识库读取流程。
- 用生产代码里 `KnowledgeLoader._find_article_spans()` 的同一个正则在沙箱里直接对
  这份文件做了真实统计（不是估算）：**当前条号数 = 26**（第一、二、三、十七、
  十九、二十、二十一、二十三、二十四、二十九、三十、三十三、三十四、三十五、
  二十二、二十五、二十六、三十六、三十九、四十、四十六、四十七、四十八、八十二、
  八十五、八十七条）。最终 BM25 文档数等于这个条号数，**除非**某一条文本长度超过
  `settings.KNOWLEDGE_CHUNK_SIZE`（500 字符）被二次切分成多个 part——这一步我没有
  在沙箱里逐条量长度确认，所以"最终文档数=26"是"没有任何条文触发二次切分"这个
  前提下的结论，不是绝对保证；第 4.2 节第 (1) 条给的命令会打印真实数字，以那个为准。
- **这个数字直接对应上这个项目历史记录里说的"baseline（26-Evidence）"知识库**——
  也就是说，生产 `data/knowledge/` 目前还停留在 baseline 版本，之前实验里用来对比
  的"working（37-Evidence）"知识库（包含额外审核过的候选条文）**从未被提升为正式
  知识库**。这不是本次 BM25 接入造成的变化，是接入前就已经存在的事实，这里只是
  借助这次统计把它明确记录下来。
- `experiment_kb/working/` 里经过前几轮实验审核的候选条文**没有**被导入
  `data/knowledge/`，本次 BM25 索引不包含它们。
- 知识库版本标识 `data/knowledge/VERSION` 仍是 `kb-2026-10-10-01`，未变。
- `data/knowledge/SOURCES.md` 记录的核验状态未变：法律文件本身的"结构核验"
  （标题/条号范围/效力状态）已通过官方来源核实，但**每条条文的"文本核验"状态仍是
  "未逐字核验"**——本次 BM25 接入只是换了一种方式读取这份文本，没有、也不可能
  重新做一次逐字核验，这个限制原样保留，不因为换成 BM25 而被悄悄"通过"。

## 4. 测试结果（严格区分"我做了什么"和"你需要做什么"）

### 4.1 我在沙箱里实际执行、确认通过的

1. **语法检查**（`python3 -m py_compile`，全部通过）：
   `rag/bm25_index.py`、`rag/retriever.py`、`rag/__init__.py`、`config/settings.py`、
   `api/dependencies.py`、`tests/test_rag_bm25_index.py`、`tests/test_api_dependencies.py`、
   `tests/test_api_full_flow.py`、`tests/test_api_contracts.py`、`tests/conftest.py`。

2. **核心逻辑的沙箱自检**（不是 pytest，是我手写的一次性脚本）：云端沙箱没有
   `langchain_core`/`langchain_chroma`/`langchain_huggingface`（尝试 `pip install` 已确认
   被网络策略拦截），所以无法直接 `import` 这个项目的 `rag` 包。我在沙箱里给
   `langchain_core.documents.Document`、`langchain_text_splitters.RecursiveCharacterTextSplitter`、
   `langchain_chroma.Chroma`、`langchain_huggingface.HuggingFaceEmbeddings` 写了最轻量的
   占位实现（只提供被用到的属性/构造签名，不含任何真实向量/数据库逻辑），让**真实的**
   `rag/bm25_index.py`、`rag/retriever.py`、`rag/knowledge_loader.py` 代码能被 import 并
   跑起来，执行了与 `tests/test_rag_bm25_index.py` 基本对应的 21 个断言，**全部通过**：
   分词器行为、空知识库/空白内容/重复条目报错且错误信息包含来源和条号、内容相似但
   不同不算重复、同条不同 part 不算重复、BM25 排序结果正确、metadata 的
   source/article/score_type 正确、k<=0 报错、与 `LegalKnowledgeRetriever` 的集成返回
   正确的 `Evidence`。
   **这不能替代真实的 `pytest` 执行**——占位的 `Document`/`Chroma` 类只模拟了被这段
   代码用到的那一小部分接口，可能和真实 `langchain_core`/`langchain_chroma` 的实际行为
   有细节差异（例如真实 `Document` 的校验、真实 `Chroma` 的各种边界情况），必须在你
   本机装好完整依赖后用真实 `pytest` 再跑一遍。

### 4.2 NOT_EXECUTED_BY_ME —— 需要你在本机运行

以下 7 项验收检查，我在本次会话里**没有任何方式实际执行**（无 `device_bash`，云端
沙箱缺依赖），都标记为 **未执行**。请在项目根目录（装好 `requirements.txt` 全部
依赖、`.env` 配好 `DEEPSEEK_API_KEY` 的环境）依次运行：

**(1) 默认配置是否真的调用 BM25（不只是配置文件写了 bm25）**

```bash
python -c "
from api.dependencies import build_app_state
from rag.bm25_index import BM25KnowledgeIndex
state = build_app_state()
assert state.embedder is None, 'embedder 应该是 None（没有加载 BGE-M3）'
assert state.knowledge_base is None, 'knowledge_base 应该是 None（没有初始化 Chroma）'
assert isinstance(state.retriever.knowledge_base, BM25KnowledgeIndex)
print('OK: 默认策略下真的在用 BM25，没有初始化 Chroma/BGE-M3，文档数 =', state.retriever.knowledge_base.count())
"
```

预期输出：`OK: 默认策略下真的在用 BM25...`，文档数应该等于 `劳动合同法.txt`
按"第X条"切分出来的条数（大于 0）。如果抛异常或 `embedder`/`knowledge_base` 不是
`None`，说明分支没生效。

**(2) BM25 和 Dense 两种配置能否分别运行**

```bash
python -c "
import config.settings as settings
settings.RETRIEVAL_STRATEGY = 'dense'
from api.dependencies import build_app_state
from rag.database import ChromaKnowledgeBase
state = build_app_state()
assert isinstance(state.knowledge_base, ChromaKnowledgeBase)
print('OK: dense 策略下真的在用 Chroma，count=', state.knowledge_base.count())
"
```

注意：这条命令会真实加载 BGE-M3（如果本机没有缓存模型权重，会触发一次真实下载），
且会打开生产 `data/chroma/`（只读查询 `count()`，不会写入/删除）。预期：不抛异常，
打印出的 `count` 应该和你已知的生产 Chroma 文档数一致。

**(3) 返回的 Evidence / 来源 / 条文编号 / metadata 是否正确**

```bash
pytest tests/test_rag_bm25_index.py -v
```

预期：全部通过（这是我在沙箱里已经用占位 Document 跑过一遍逻辑、21/21 通过的那一批
断言，但这次是用真实的 `langchain_core.documents.Document`）。

**(4) 服务重启 / 空知识库 / 索引构建失败时的行为**

```bash
pytest tests/test_api_dependencies.py -v -k "bm25 or empty_knowledge_dir or invalid_retrieval_strategy"
```

预期：`test_build_app_state_wires_bm25_backend_when_strategy_is_bm25`、
`test_build_app_state_raises_on_empty_knowledge_dir_under_bm25`、
`test_build_app_state_rejects_invalid_retrieval_strategy` 全部通过。
"重启"本身（真的重启一次 `uvicorn api.app:app`，确认两次启动行为一致）我没有
环境可以验证，需要你手动跑一次确认。

**(5) 现有相关测试和回归测试是否通过**

```bash
pytest
```

预期：全部通过，包括改动前就存在的全部测试（`test_api_dependencies.py`、
`test_api_full_flow.py`、`test_api_contracts.py` 里原有的测试已经显式钉回
`RETRIEVAL_STRATEGY="dense"`，理论上行为应该和接入前完全一致；但"理论上"不等于
"已验证"，这条必须你本机跑一遍才算数）。

**(6) 正式知识库更新前后：文档数量 / 内容指纹 / 条文映射 / 重复情况**

本轮**没有更新**正式知识库内容（见第 3 节），所以严格来说"更新前后对比"不适用。
如果你想确认"BM25 读到的条文数量"这一项：

```bash
python -c "
from config import settings
from rag.knowledge_loader import KnowledgeLoader
evidences = KnowledgeLoader(knowledge_base=None).load_directory(settings.KNOWLEDGE_DIR)
print('条文数:', len(evidences))
for e in evidences:
    print(' ', e.source, e.article)
"
```

这个数字目前没有一份"接入前的基线记录"可以对比（此前的实验都是在
`experiment_kb/working/`、`experiment_kb/baseline/` 这两份独立的实验知识库副本上跑的，
不是生产 `data/knowledge/`），所以这里只能报告"当前值是多少"，不能说"和接入前相比
有没有变化"——如果你需要这个基线，我可以另外去读一次 `data/knowledge/劳动合同法.txt`
算出当前条数作为"本次接入时刻"的基线记录。

**(7) 能否通过恢复旧配置和旧知识库版本完成回滚**

```bash
# 回滚方式一：只改配置，不改代码
# 把 config/settings.py 里的 RETRIEVAL_STRATEGY 改回 "dense"，重启服务。
# 预期：Chroma 构造代码完全未被触碰，行为与接入前逐字一致。

# 回滚方式二：代码回滚
git diff --stat   # 确认本次改动只涉及上面"改动文件清单"里列出的文件
git checkout -- rag/bm25_index.py config/settings.py api/dependencies.py \
    rag/retriever.py rag/__init__.py tests/conftest.py \
    tests/test_api_dependencies.py tests/test_api_full_flow.py tests/test_api_contracts.py \
    tests/test_rag_bm25_index.py
# 或者直接 git revert 本次提交。
```

`data/chroma/`、`data/knowledge/` 本轮从未被写入，不需要任何数据层面的回滚。

## 5. 遗留风险 / 已知瑕疵（没有编造，都是写代码时实际做出的权衡）

1. **`KnowledgeLoader(knowledge_base=None)`**：BM25 路径为了复用
   `KnowledgeLoader.load_directory()` 的"读文件→切分"逻辑，构造时给必填的
   `knowledge_base` 参数传了 `None`。这是安全的（`load_directory`/`load_file`/
   `split_text` 从不触碰 `self.knowledge_base`，只有 `index()`/`load_and_index_*()`
   才会用到它，BM25 路径不调用那些写入方法），但类型标注上是个瑕疵。更干净的做法是
   把"读取/切分"这部分方法改成不依赖 `knowledge_base` 的 `staticmethod`/独立函数，
   但那是对 `rag/knowledge_loader.py` 的改动，超出本轮批准的改动范围，留作后续建议。

2. **复用了 `KnowledgeLoader` 的两个带下划线前缀的 staticmethod**
   （`_evidence_id`、`_to_metadata`）：Python 不做访问限制，这样调用是为了让"判重
   哈希公式"只在一个地方维护，不在两处各写一遍、以后悄悄跑偏。更干净的做法是把它们
   提升为 `KnowledgeLoader` 的公开方法，这也是对 `knowledge_loader.py` 的改动，本轮
   没有做。

3. **`score_type` 目前只在 BM25 路径的 metadata 里被打上标记**
   （`"bm25_okapi_char_bigram"`），Dense 路径（`rag/database.py`）没有对应打
   `"score_type": "chroma_distance"` 之类的标记，因为这需要改 `rag/database.py`，
   不在本轮批准范围内。已确认当前生产代码（`prompts/review.py`、
   `rag/retriever.py`）没有任何地方对 `Evidence.metadata["score"]` 做跨策略的数值
   比较，所以这不是一个正在发生的 bug，只是"以后如果有人想比较两种策略的分数"
   需要先注意这个不对称。

4. **BM25 索引不持久化，每次应用启动都要重新读文件+重新建索引**：对当前只有一个
   10KB 文件的生产知识库来说，这个耗时可以忽略；如果以后知识库明显变大，需要关注
   启动耗时（这是用户本轮方案里"不单独持久化"的明确决定，不是本次改动引入的意外
   行为，这里只是记录下来供以后评估）。

5. **"重复条目报错 vs 静默去重"是本轮按你的决定（第 2 点）选择报错**，与
   `KnowledgeLoader.index()` 写入 Chroma 时的"批内去重保留第一条"行为不是同一套
   语义——这是刻意的两套不同场景下的不同选择（"写入数据库"场景选择去重更宽松，
   "构建检索索引"场景选择报错更保守），不是遗漏。

## 6. 已知诊断案例重申

"工作地点单方调整 + 第二十六条"双通道漏检案例（见
`docs/ART26_WORKPLACE_RELOCATION_DIAGNOSIS.md`）：BM25（char_bigram）零字符二元组
重合这个结论在之前的诊断里已经用真实计算证实，**本次 BM25 正式接入没有、也不可能
解决这个案例**——根因是这条具体 query 和这条具体法条之间的词汇表完全不重合，与
"是不是正式接入了 BM25"无关；该场景的法律相关性标签本身也仍然是人工未核验状态。
不会把这个案例写成"已解决"。

## 7. 开发日志（实际发生的事，没有编造）

- 写 `rag/bm25_index.py` 前，重新读取了 `experiment_kb/scripts/eval_working_kb_retrieval.py`
  里 `_BM25Index`/`_char_bigram_tokenizer()` 的真实源码，逐行对照搬过来，避免凭记忆
  重新实现导致和已经验证过的算法产生细微偏差。
- 读取 `tests/test_api_dependencies.py`/`test_api_full_flow.py`/`test_api_contracts.py`
  时发现，这三个文件的 `_patch_heavy_builders()` 都无条件期望 `build_app_state()`
  会调用 `ChromaKnowledgeBase`/`build_embedder`——如果让生产默认值变成 `"bm25"` 而不
  调整这三个文件，原有的 `test_build_app_state_wires_existing_modules_together`
  等测试会直接断言失败（`state.knowledge_base` 会是 `None` 而不是
  `ChromaKnowledgeBase` 实例）。处理方式是在这三个文件的 `_patch_heavy_builders()`
  里显式把 `RETRIEVAL_STRATEGY` 钉回 `"dense"`，让它们继续测试原本要测的 Dense 路径，
  同时新增专门测 BM25 路径的测试。
- 往 `/mnt/user-data/outputs/.../rag/retriever.py` 写文件时第一次被工具拒绝
  （"File has not been read yet"）——发现这个输出目录下已经留有上一轮会话写过的
  同路径文件缓存，按工具要求先 `Read` 一遍确认内容和设备上一致，再覆盖写入。
- 云端沙箱尝试 `pip install langchain-core` 被网络策略拦截（DNS 解析失败），
  确认了会话总结里记录的"云端沙箱无法装 chromadb/BGE-M3 等重依赖"这条限制同样
  适用于 `langchain_core`，于是改用本报告第 4.1 节里说明的"占位模块"方式做部分验证。
- 确认 `schemas/evidence.py` 的 `Evidence.content` 字段只校验 `min_length=1`，
  不校验"是否全是空白字符"——这是 `BM25KnowledgeIndex` 自己必须补一道空白内容检查
  的原因（否则全是空格的 `content` 能通过 Evidence 的校验，混进 BM25 索引）。

## 8. 知识树更新建议

- `KnowledgeLoader` 里 `_evidence_id()`/`_to_metadata()` 建议提升为公开方法/独立函数：
  现在已经有两个使用方（`index()` 和 `BM25KnowledgeIndex`）依赖同一套哈希/metadata
  口径，继续用带下划线前缀的"私有"方法调用，长期看是个一致性风险点。
- 建议把"BM25 索引构建耗时"纳入以后知识库扩容时的常规检查项（本轮 10KB 单文件下
  可忽略，数据量上去后需要重新评估"每次启动重建"是否还合适）。
- `data/knowledge/SOURCES.md` 的"文本未逐字核验"状态，建议在后续任何一次知识库
  扩容工作开始前，作为一个独立的阻塞项先处理掉，而不是继续累积。

## 9. 待办

- [ ] 你在本机运行第 4.2 节列出的 7 条命令，把结果反馈给我（或自行确认）。
- [ ] 如果需要"接入前后知识库条数对比"的基线记录，告诉我，我可以另外读一次
  `data/knowledge/劳动合同法.txt` 算出当前条数存档。
- [ ] 知识库正式扩容（引入 `experiment_kb/working/` 候选内容）按你的要求本轮不做，
  需要你另外下达指令时再进行，且需要先列出版本核验等阻塞项。
