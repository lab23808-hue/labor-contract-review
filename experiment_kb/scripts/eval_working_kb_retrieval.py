"""experiment_kb/working/ 专用：Dense / BM25 / Dense+BM25+RRF 检索策略实验
（统一实验入口，不新建 experiment_kb_v4/v5）。

【为什么新增这一个脚本，而不是直接改 eval_retrieval_strategy_experiment.py】
    真实项目里已经验证能跑的 `scripts/eval_retrieval_strategy_experiment.py`
    把知识库来源硬编码成 `settings.KNOWLEDGE_DIR`（正式 `data/knowledge/`），
    Dense 通道默认优先"复用上一轮基于 26 条 Evidence 跑出的历史结果"。这两点
    都和本轮要求冲突：
        a) 本轮必须用 `experiment_kb/working/`（37 条 Evidence：生产 26 条 +
           新增《劳动合同法》第五十条 1 条 + 《劳动法》第三十六—四十五条 10 条），
           不能改 `settings.KNOWLEDGE_DIR` 去指向它（那样等于临时改动了正式配置）；
        b) 本轮明确不允许"把旧版 26 条 Evidence 上的 Dense 历史结果直接当成本轮
           基线"——37 条 Evidence 的知识库内容和 26 条完全不同，复用逻辑在这里
           没有意义，必须强制真实重跑 Dense。
    所以新增一个独立入口，但 BM25 索引实现（`_BM25Index`）、RRF 融合公式
    （`_rrf_fuse`）、评估公式（`_dcg`/`_score`/`_aggregate`）三部分，直接原样
    复用 `eval_retrieval_strategy_experiment.py` 里已经跑通、已经核对过的实现，
    不重新发明一套，只改了"知识库来源"和"Dense 是否复用"这两处。

【固定输入（本轮不可更改，详见 experiment_kb/README.md 和 WHITELIST_current.md）】
    - 知识库：experiment_kb/working/data/knowledge/*.txt
      （劳动合同法.txt 原文 + LAW_01_劳动合同法_第五十条.txt +
       LAW_02_劳动法_第三十六条至第四十五条.txt，共 37 条 Evidence，
       已用 build_snapshot_fingerprint.py 记录指纹
       5bce72e5b4169939b25a0fbf169dc9e133ee2b2843040312c4267b9f51c8fd61f —
       见 experiment_kb/snapshots/working_snapshot.json）。
    - 评估数据：experiment_kb/working/data/eval_samples/retrieval_eval_samples.json
      （和生产 data/eval_samples/ 下的文件字节级相同，188 条有效样本 /
       47 个独立场景，diff_snapshots() 已确认 eval_dataset_changed=False，
       本脚本不重新生成、不重新调用 generate_query()）。
    - 仲裁法候选材料（experiment_kb/reference_only/）**不会**被这个脚本读取——
      本脚本只 glob `working/data/knowledge/`，reference_only/ 不在这个路径下，
      启动时会额外断言 knowledge 目录里不存在任何文件名包含"仲裁"的文件，
      双重防止参考材料意外混入核心检索索引。

【运行前提（本脚本本身不安装依赖，只检查）】
    需要真实 langchain_chroma / langchain_huggingface / sentence-transformers /
    chromadb，以及联网下载（或已缓存）BGE-M3 权重。BM25 的 jieba 分词器可选，
    没装会自动退化为字符级 2-gram 并在结果里明确标注 tokenizer_used。
    云端沙箱环境已实测确认无法安装上述依赖（pypi.org/registry.npmjs.org 均
    被组织网络策略拒绝，DNS 也无法直连解析），所以本脚本**只能在你本机、已经
    装好这些依赖的 venv 里运行**，不能在这次会话里直接执行——这一点本脚本的
    说明文字和交付报告里都会如实标注"尚未实际运行"。

【安全隔离（比真实项目里的版本更严格一层：临时数据必须落在实验目录内部，
  不能用系统 /tmp，防止"实验数据到底存在哪"这件事本身也变得不可追溯）】
    - Dense 临时 Chroma 持久化目录：experiment_kb/tmp_runtime/dense_<时间戳>/
      （不是 tempfile.mkdtemp() 的系统临时目录）。
    - collection 名：f"experiment_kb_working_dense_{时间戳}"，启动时断言
      既不等于 settings.CHROMA_COLLECTION_NAME，也不等于 settings.CHROMA_DIR
      的路径或其子路径——撞了直接 AssertionError 中止，不运行。
    - 全部运行结束后（含异常退出的 finally 块）清理 experiment_kb/tmp_runtime/
      下本次产生的子目录，不在实验目录里累积垃圾。
    - 不修改、不调用任何正式 `rag/retriever.py` / `rag/database.py` /
      `agents/review_agent.py` / `generate_query()` 的逻辑；不打开正式
      `data/chroma`（甚至不像 eval_retrieval_strategy_experiment.py 那样做
      只读核验——因为这次知识库内容本身就和官方库不同，没有"核对是否一致"
      这个问题，核对历史 26 条基线的任务留给生产库自己的脚本）。

【本轮要求的六项性能测量，在结果 JSON 的 `performance` 字段里逐项对应】
    1. dense_query_embedding_and_retrieval      Dense 单次检索延迟列表 + P50/P95
    2. bm25_tokenization_and_ranking            BM25 单次检索延迟列表 + P50/P95
    3. rrf_fusion_overhead                      RRF 融合 47 个场景的总耗时/均摊耗时
    4. hybrid_end_to_end                        serial（Dense+BM25 顺序执行+RRF）
                                                 和 parallel（线程池并发跑 Dense/BM25
                                                 两个通道后再 RRF）两种耗时都记录，
                                                 parallel 只是"query 级别的墙钥时间
                                                 是否有重叠收益"的工程测量，不代表
                                                 生产架构会这样部署。
    5. index_build_update_delete                Dense/BM25 两个索引各自的：首次构建、
                                                 新增 1 条 Evidence 后的更新、删除 1 条
                                                 Evidence 后的删除，三个操作各自的真实
                                                 耗时（不是估算）。
    6. cold_start_and_model_init                embedder_load_seconds（BGE-M3 模型加载，
                                                 和知识库构建/检索分开单独计时）。

【质量指标口径】
    Recall@5 / Recall@10 / MRR / nDCG@10，candidate_k=20 用于 Top-20 漏检诊断
    （relevant pair 在 Dense 和 BM25 各自 candidate_k=20 候选里都没出现，RRF
    不可能把它变出来——按原脚本的说明，这是上游漏检，不是融合算法的问题）。
    同时报告"原始样本口径(188)"和"独立场景口径(47，等权重)"两套数字。
    **标准答案尚未全部人工核验**：输出 JSON 顶层 `caveats` 字段和 markdown
    报告开头都会显式写明这一限制，不把本轮指标称为"最终真实 Recall"，只是
    "阶段性、基于当前（尚待完善人工核验的）标准答案标签算出的指标"。

【运行】
    python experiment_kb/scripts/eval_working_kb_retrieval.py
    可选参数：
        --rrf-k <int>            覆盖默认 rrf_k=60
        --skip-index-mutation    跳过"索引更新/删除耗时测试"这一步（更快跑完，
                                  用于先确认检索指标，性能测量第5项会标注跳过）
        --output <path>          覆盖默认输出 JSON 路径

【预期输出】
    - experiment_kb/results/working_kb_retrieval_experiment_<时间戳>.json
      （完整结果：逐场景候选、逐场景三种策略在 top5/10/20 的得分、performance
       六项测量、knowledge/eval 快照指纹核对结果）
    - experiment_kb/results/working_kb_retrieval_experiment_<时间戳>.md
      （给人看的简短报告）

【异常处理】
    任何依赖缺失（chromadb/langchain_chroma/langchain_huggingface 没装，或
    BGE-M3 下不下来）会在 `embedder = build_embedder()` 这一步直接抛出真实
    异常并中止整个脚本（sys.exit(1) 前打印清晰原因），不会静默降级成"假结果"
    或跳过 Dense 通道只跑 BM25。知识库/评估数据指纹核对失败（运行前或运行后
    发现 experiment_kb/working/ 内容被改动）也会直接中止并打印具体差异，不会
    继续跑一个"输入已经变了"的实验。
"""

import argparse
import concurrent.futures
import json
import math
import shutil
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

SCRIPT_PATH = Path(__file__).resolve()
EXPERIMENT_DIR = SCRIPT_PATH.parent.parent          # .../experiment_kb/
PROJECT_ROOT = EXPERIMENT_DIR.parent                 # 真实项目根目录
# 下面四个变量默认指向 working/（37条Evidence），--kb-source baseline 时
# main() 会在调用 run() 之前把它们重新指向 baseline/（26条Evidence只读基线）。
# 这是本轮"用同一套代码公平对比 baseline/working"要求的最小必要改动：不复制一份
# 检索逻辑，只是让同一套函数在运行前指向不同的知识库/评估集/快照记录路径——
# 函数内部都是在调用时按模块全局变量取值，不是在定义时捕获，所以这样重新赋值
# 对所有已有函数都生效，不需要逐个函数加参数。
WORKING_DIR = EXPERIMENT_DIR / "working"
WORKING_KNOWLEDGE_DIR = WORKING_DIR / "data" / "knowledge"
WORKING_SAMPLES_PATH = WORKING_DIR / "data" / "eval_samples" / "retrieval_eval_samples.json"
RECORDED_WORKING_SNAPSHOT_PATH = EXPERIMENT_DIR / "snapshots" / "working_snapshot.json"
RESULTS_DIR = EXPERIMENT_DIR / "results"
TMP_RUNTIME_DIR = EXPERIMENT_DIR / "tmp_runtime"
KB_SOURCE_LABEL = "working"  # main() 会按 --kb-source 改成 "baseline"，用于文件名前缀和结果字段

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))  # 复用 build_snapshot_fingerprint.py

from config import settings  # noqa: E402

CANDIDATE_K = 20
FINAL_TOP_KS = [5, 10, 20]
DEFAULT_RRF_K = 60


# ======================================================================
# 0. 启动前检查：输入必须是 experiment_kb/working/ 本身，且内容没有被改动
# ======================================================================

def _assert_no_arbitration_leak() -> None:
    if not WORKING_KNOWLEDGE_DIR.exists():
        raise SystemExit(f"找不到 {WORKING_KNOWLEDGE_DIR}，请先确认 experiment_kb/working/ 已经构建。")
    for f in WORKING_KNOWLEDGE_DIR.glob("*.txt"):
        if "仲裁" in f.name:
            raise SystemExit(
                f"发现仲裁法文件混入核心检索知识库目录：{f}。"
                "按白名单规则，仲裁法第十—十六条只能留在 experiment_kb/reference_only/，"
                "不得进入 experiment_kb/working/ 核心索引——已中止，未运行任何检索。"
            )


def _verify_working_snapshot_unchanged(stage: str) -> dict:
    """运行前/运行后都重新算一次 experiment_kb/working 的快照，和
    experiment_kb/snapshots/working_snapshot.json 里记录的指纹比较。
    不一致就直接报告差异（运行前发现不一致会中止；运行后发现不一致只记录
    到结果 JSON 里，因为那时检索已经跑完，但必须让使用者知道"这次用的输入
    和记录的不是同一个版本"）。
    """
    import build_snapshot_fingerprint as bsf  # noqa: E402

    if not RECORDED_WORKING_SNAPSHOT_PATH.exists():
        return {
            "checked": False,
            "reason": f"找不到 {RECORDED_WORKING_SNAPSHOT_PATH}，无法比对指纹",
        }
    recorded = json.loads(RECORDED_WORKING_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    current = bsf.build_full_snapshot(WORKING_DIR, note=f"eval_working_kb_retrieval.py:{stage}")
    diff = bsf.diff_snapshots(recorded, current)
    return {
        "checked": True,
        "stage": stage,
        "recorded_fingerprint": recorded.get("overall_content_fingerprint"),
        "current_fingerprint": current.get("overall_content_fingerprint"),
        "changed": diff.get("overall_changed"),
        "diff": diff,
    }


# ======================================================================
# 1. 评估样本 / 场景加载（和 eval_retrieval_strategy_experiment.py 完全相同的分组逻辑）
# ======================================================================

def _load_evaluable_samples() -> list[dict]:
    if not WORKING_SAMPLES_PATH.exists():
        raise SystemExit(f"找不到 {WORKING_SAMPLES_PATH}")
    payload = json.loads(WORKING_SAMPLES_PATH.read_text(encoding="utf-8"))
    return [s for s in payload["samples"] if s["evaluable"]]


def _label_key(sample: dict) -> tuple:
    return tuple(sorted((r["source"], r["article"]) for r in sample["relevant"]))


def _build_scenarios(evaluable: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = {}
    for s in evaluable:
        key = (s["query"], _label_key(s))
        grouped.setdefault(key, []).append(s)
    scenarios = []
    for (query, label_key), members in grouped.items():
        scenarios.append(
            {
                "query": query,
                "relevant_pairs": [list(p) for p in label_key],
                "member_sample_ids": [m["sample_id"] for m in members],
                "occurrence_count": len(members),
            }
        )
    return scenarios


# ======================================================================
# 2. Dense 通道：强制真实重跑（本轮规则：不允许复用旧 26 条 Evidence 的结果）
# ======================================================================

def _assert_isolated_from_official_db(persist_dir: Path, collection_name: str) -> None:
    official_dir = settings.CHROMA_DIR.resolve()
    temp_dir = persist_dir.resolve()
    assert temp_dir != official_dir, f"临时持久化目录和正式目录撞了：{temp_dir}，已中止"
    assert not str(temp_dir).startswith(str(official_dir)), f"临时目录在正式目录内部：{temp_dir}，已中止"
    assert collection_name != settings.CHROMA_COLLECTION_NAME, (
        f"临时 collection 名字和正式名字（{settings.CHROMA_COLLECTION_NAME}）相同，已中止"
    )
    assert str(temp_dir).startswith(str(EXPERIMENT_DIR.resolve())), (
        f"临时目录没有落在 experiment_kb/ 内部：{temp_dir}，按本轮要求中止"
    )


def _load_working_knowledge_evidences() -> list:
    """用和生产 KnowledgeLoader 完全相同的切分逻辑，切分 experiment_kb/working/
    的知识文本（不是生产 data/knowledge/）。不写入任何数据库，纯内存操作。
    """
    from rag.knowledge_loader import KnowledgeLoader, _SEPARATORS
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    loader = KnowledgeLoader.__new__(KnowledgeLoader)
    loader.chunk_size = settings.KNOWLEDGE_CHUNK_SIZE
    loader.chunk_overlap = settings.KNOWLEDGE_CHUNK_OVERLAP
    loader._splitter = RecursiveCharacterTextSplitter(
        chunk_size=loader.chunk_size,
        chunk_overlap=loader.chunk_overlap,
        separators=_SEPARATORS,
        is_separator_regex=True,
        keep_separator="end",
        strip_whitespace=True,
    )
    return loader.load_directory(WORKING_KNOWLEDGE_DIR)


def _run_dense_channel(scenarios: list[dict], knowledge_evidences: list, skip_index_mutation: bool) -> tuple[dict, dict]:
    """真实调用 BGE-M3 + 临时 Chroma（落在 experiment_kb/tmp_runtime/ 内部）。
    返回 (每个场景 candidate_k=20 的 Dense 候选, 性能测量字典)。
    """
    from rag import ChromaKnowledgeBase, KnowledgeLoader, LegalKnowledgeRetriever, build_embedder

    TMP_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    persist_dir = TMP_RUNTIME_DIR / f"dense_{timestamp}"
    collection_name = f"experiment_kb_working_dense_{timestamp}"
    _assert_isolated_from_official_db(persist_dir, collection_name)

    perf: dict = {}
    try:
        t0 = time.perf_counter()
        embedder = build_embedder()
        perf["cold_start_and_model_init"] = {"embedder_load_seconds": round(time.perf_counter() - t0, 3)}

        t1 = time.perf_counter()
        kb = ChromaKnowledgeBase(embedder, persist_directory=persist_dir, collection_name=collection_name)
        loader = KnowledgeLoader(kb)
        loader.index(knowledge_evidences)
        build_seconds = round(time.perf_counter() - t1, 3)
        doc_count_after_build = kb.count()

        index_mutation: dict = {
            "initial_build_seconds": build_seconds,
            "initial_doc_count": doc_count_after_build,
        }

        if not skip_index_mutation and knowledge_evidences:
            probe = knowledge_evidences[0]
            t_upd = time.perf_counter()
            loader.index([probe])  # 以同一条 Evidence 重新写入，模拟"更新"
            index_mutation["update_one_evidence_seconds"] = round(time.perf_counter() - t_upd, 3)
            index_mutation["doc_count_after_update"] = kb.count()

            try:
                from rag.knowledge_loader import KnowledgeLoader as _KL
                probe_id = _KL._evidence_id(probe)
                t_del = time.perf_counter()
                kb._store._collection.delete(ids=[probe_id])  # ChromaKnowledgeBase 没有公开的 delete()
                # 方法，只有内部 _store（langchain_chroma.Chroma）.delete_collection()
                # 这种整体清空；这里要测的是"删除单条文档"，和 count() 方法本身
                # 用同样的方式（见 rag/database.py 的 count()）访问底层
                # self._store._collection（真正的 chromadb Collection 对象），
                # 不是新发明一个接口。
                index_mutation["delete_one_evidence_seconds"] = round(time.perf_counter() - t_del, 3)
                index_mutation["doc_count_after_delete"] = kb.count()
            except Exception as exc:  # noqa: BLE001 - 如实记录，不假装删除测试成功
                index_mutation["delete_test_error"] = (
                    f"删除测试失败，如实记录，不影响检索指标本身: {exc!r}"
                )
        else:
            index_mutation["skipped"] = True

        perf["index_build_update_delete"] = {"dense": index_mutation}

        retriever = LegalKnowledgeRetriever(kb)
        candidates_by_key: dict[tuple, list[dict]] = {}
        per_query_seconds: list[float] = []
        for sc in scenarios:
            key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
            t2 = time.perf_counter()
            retrieved = retriever.search_legal_knowledge(sc["query"], k=CANDIDATE_K)
            elapsed = time.perf_counter() - t2
            per_query_seconds.append(elapsed)
            candidates_by_key[key] = [
                {"source": e.source, "article": e.article, "score": e.metadata.get("score")} for e in retrieved
            ]

        dense_perf = {
            "distinct_query_count": len(per_query_seconds),
            "total_seconds": round(sum(per_query_seconds), 3),
            "mean_seconds": round(statistics.mean(per_query_seconds), 4) if per_query_seconds else None,
            "p50_seconds": round(statistics.median(per_query_seconds), 4) if per_query_seconds else None,
            "p95_seconds": (
                round(statistics.quantiles(per_query_seconds, n=100)[94], 4)
                if len(per_query_seconds) > 1 else None
            ),
            "raw_seconds": [round(s, 5) for s in per_query_seconds],
        }
        perf["dense_query_embedding_and_retrieval"] = dense_perf
        return candidates_by_key, perf
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)


# ======================================================================
# 3. BM25 通道：原样复用 eval_retrieval_strategy_experiment.py 的实现
# ======================================================================

def _char_bigram_tokenizer() -> Callable[[str], list[str]]:
    def _tok(text: str) -> list[str]:
        chars = [c for c in text if not c.isspace()]
        if len(chars) <= 1:
            return chars
        return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]

    return _tok


def _get_tokenizer(force: Optional[str] = None) -> tuple[str, Callable[[str], list[str]]]:
    """force=None：自动探测（装了 jieba 用 jieba，没装退化 char_bigram，和历史脚本
    行为一致）。force="jieba"：显式要求 jieba，没装就直接报错退出，不静默退化成
    别的分词器——"明确切换分词器"这个指令要求的是真的换了那一种，不是"尽力而为"。
    force="char_bigram"：显式强制字符二元组，即使本机装了 jieba 也不使用它——
    这是本轮"补跑 char_bigram 对照"需要的路径。
    """
    if force == "char_bigram":
        return "char_bigram (forced via --tokenizer char_bigram)", _char_bigram_tokenizer()
    if force == "jieba":
        import jieba  # type: ignore  # 没装会在这里直接 ImportError 中止，不降级

        def _tok(text: str) -> list[str]:
            return [t for t in jieba.cut(text) if t.strip()]

        return "jieba (forced via --tokenizer jieba)", _tok

    try:
        import jieba  # type: ignore

        def _tok(text: str) -> list[str]:
            return [t for t in jieba.cut(text) if t.strip()]

        return "jieba", _tok
    except ImportError:
        def _tok(text: str) -> list[str]:
            chars = [c for c in text if not c.isspace()]
            if len(chars) <= 1:
                return chars
            return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]

        return "char_bigram (jieba not installed)", _tok


def _load_knowledge_documents_for_bm25(evidences: list) -> list[dict]:
    merged: dict[tuple, list[str]] = {}
    for e in evidences:
        key = (e.source, e.article)
        merged.setdefault(key, []).append(e.content)
    docs = []
    for (source, article), parts in merged.items():
        docs.append({"source": source, "article": article, "text": "".join(parts)})
    return docs


class _BM25Index:
    """标准 BM25Okapi（k1=1.5, b=0.75），纯标准库实现（与
    eval_retrieval_strategy_experiment.py 中的实现逐行一致，不重新发明）。"""

    def __init__(self, docs: list[dict], tokenize) -> None:
        self.docs = docs
        self.tokenize = tokenize
        self.k1 = 1.5
        self.b = 0.75
        self.doc_tokens: list[list[str]] = [tokenize(d["text"]) for d in docs]
        self.doc_lens = [len(toks) for toks in self.doc_tokens]
        self.avgdl = statistics.mean(self.doc_lens) if self.doc_lens else 0.0
        self.N = len(docs)
        self.df: dict[str, int] = {}
        self.doc_tf: list[dict[str, int]] = []
        for toks in self.doc_tokens:
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self.doc_tf.append(tf)
            for t in tf:
                self.df[t] = self.df.get(t, 0) + 1
        self.idf: dict[str, float] = {
            t: math.log((self.N - df + 0.5) / (df + 0.5) + 1.0) for t, df in self.df.items()
        }

    def search(self, query: str, k: int) -> list[dict]:
        q_tokens = self.tokenize(query)
        scores = [0.0] * self.N
        for i in range(self.N):
            tf = self.doc_tf[i]
            dl = self.doc_lens[i]
            denom_norm = self.k1 * (1 - self.b + self.b * (dl / self.avgdl if self.avgdl else 0))
            score = 0.0
            for t in q_tokens:
                if t not in tf:
                    continue
                idf = self.idf.get(t, 0.0)
                freq = tf[t]
                score += idf * (freq * (self.k1 + 1)) / (freq + denom_norm)
            scores[i] = score
        order = sorted(range(self.N), key=lambda i: (-scores[i], i))
        top = order[:k]
        return [
            {"source": self.docs[i]["source"], "article": self.docs[i]["article"], "score": round(scores[i], 6)}
            for i in top
        ]

    def add_document(self, doc: dict) -> None:
        """性能测量第5项用：给索引新增一条文档后，重建统计量（BM25Okapi 的
        idf/avgdl 依赖全局统计，没有"增量更新"这个概念，诚实地整体重建，
        不假装有增量算法。"""
        self.docs.append(doc)
        self.__init__(self.docs, self.tokenize)

    def remove_document(self, source: str, article: str) -> None:
        self.docs = [d for d in self.docs if not (d["source"] == source and d["article"] == article)]
        self.__init__(self.docs, self.tokenize)


def _run_bm25_channel(
    scenarios: list[dict], knowledge_evidences: list, skip_index_mutation: bool, tokenizer_force: Optional[str] = None
) -> tuple[dict, dict, str]:
    bm25_docs = _load_knowledge_documents_for_bm25(knowledge_evidences)
    tokenizer_name, tokenize = _get_tokenizer(force=tokenizer_force)

    t_build = time.perf_counter()
    bm25_index = _BM25Index(bm25_docs, tokenize)
    build_seconds = round(time.perf_counter() - t_build, 3)

    index_mutation: dict = {"initial_build_seconds": build_seconds, "initial_doc_count": len(bm25_docs)}
    if not skip_index_mutation and bm25_docs:
        probe = bm25_docs[0]
        t_upd = time.perf_counter()
        bm25_index.add_document({"source": probe["source"], "article": probe["article"], "text": probe["text"] + " "})
        index_mutation["update_one_document_seconds"] = round(time.perf_counter() - t_upd, 3)
        index_mutation["doc_count_after_update"] = bm25_index.N

        t_del = time.perf_counter()
        bm25_index.remove_document(probe["source"], probe["article"])
        index_mutation["delete_one_document_seconds"] = round(time.perf_counter() - t_del, 3)
        index_mutation["doc_count_after_delete"] = bm25_index.N
    else:
        index_mutation["skipped"] = True

    candidates_by_key: dict[tuple, list[dict]] = {}
    per_query_seconds: list[float] = []
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        t1 = time.perf_counter()
        candidates_by_key[key] = bm25_index.search(sc["query"], CANDIDATE_K)
        per_query_seconds.append(time.perf_counter() - t1)

    perf = {
        "distinct_query_count": len(per_query_seconds),
        "total_seconds": round(sum(per_query_seconds), 3),
        "mean_seconds": round(statistics.mean(per_query_seconds), 4) if per_query_seconds else None,
        "p50_seconds": round(statistics.median(per_query_seconds), 4) if per_query_seconds else None,
        "p95_seconds": (
            round(statistics.quantiles(per_query_seconds, n=100)[94], 4) if len(per_query_seconds) > 1 else None
        ),
        "raw_seconds": [round(s, 5) for s in per_query_seconds],
        "index_build_update_delete": index_mutation,
    }
    return candidates_by_key, perf, tokenizer_name


# ======================================================================
# 4. RRF 融合（原样复用）
# ======================================================================

def _rrf_fuse(dense_candidates: list[dict], bm25_candidates: list[dict], rrf_k: int, limit: int) -> list[dict]:
    dense_rank = {(d["source"], d["article"]): i + 1 for i, d in enumerate(dense_candidates)}
    bm25_rank = {(d["source"], d["article"]): i + 1 for i, d in enumerate(bm25_candidates)}
    all_keys = set(dense_rank) | set(bm25_rank)
    fused = []
    for key in all_keys:
        dr = dense_rank.get(key)
        br = bm25_rank.get(key)
        score = (1.0 / (rrf_k + dr) if dr else 0.0) + (1.0 / (rrf_k + br) if br else 0.0)
        rank_sum = (dr or 10**6) + (br or 10**6)
        fused.append((key, score, rank_sum, dr or 10**6))
    fused.sort(key=lambda x: (-x[1], x[2], x[3]))
    return [
        {"source": k[0], "article": k[1], "score": round(score, 6), "from_dense": k in dense_rank, "from_bm25": k in bm25_rank}
        for (k, score, _, _) in fused[:limit]
    ]


# ======================================================================
# 5. 评估公式（原样复用）
# ======================================================================

def _dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def _score(relevant_pairs: set, retrieved_pairs: list, k: int) -> dict:
    window = retrieved_pairs[:k]
    hit_positions = [i + 1 for i, pair in enumerate(window) if pair in relevant_pairs]
    distinct_hits = {pair for pair in window if pair in relevant_pairs}
    recall = len(distinct_hits) / len(relevant_pairs) if relevant_pairs else None
    first_rank = hit_positions[0] if hit_positions else None
    mrr_contrib = 1.0 / first_rank if first_rank else 0.0
    rels = [1 if pair in relevant_pairs else 0 for pair in window]
    dcg = _dcg(rels)
    idcg = _dcg([1] * min(len(relevant_pairs), k))
    ndcg = dcg / idcg if idcg > 0 else None
    return {"recall": recall, "mrr_contribution": mrr_contrib, "first_hit_rank": first_rank, "ndcg": ndcg}


def _aggregate(rows: list[dict]) -> dict:
    recalls = [r["recall"] for r in rows if r["recall"] is not None]
    mrrs = [r["mrr_contribution"] for r in rows]
    ndcgs = [r["ndcg"] for r in rows if r["ndcg"] is not None]
    return {
        "n": len(rows),
        "recall": round(statistics.mean(recalls), 4) if recalls else None,
        "mrr": round(statistics.mean(mrrs), 4) if mrrs else None,
        "ndcg": round(statistics.mean(ndcgs), 4) if ndcgs else None,
    }


def _find_top20_misses(scenarios: list[dict], dense_by_key: dict, bm25_by_key: dict) -> list[dict]:
    """诊断：relevant pair 在 Dense 和 BM25 各自 candidate_k=20 里都没出现的场景
    ——按原脚本的说明，这种情况 RRF 无论怎么融合都不可能找回，属于上游漏检。
    """
    misses = []
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        relevant_pairs = set(key[1])
        dense_pairs = {(d["source"], d["article"]) for d in dense_by_key[key]}
        bm25_pairs = {(d["source"], d["article"]) for d in bm25_by_key[key]}
        never_recalled = relevant_pairs - dense_pairs - bm25_pairs
        if never_recalled:
            misses.append(
                {
                    "query": sc["query"],
                    "relevant_pairs": sc["relevant_pairs"],
                    "member_sample_ids": sc["member_sample_ids"],
                    "never_recalled_by_either_channel": sorted(never_recalled),
                }
            )
    return misses


# ======================================================================
# 6. 主流程
# ======================================================================

def _try_reuse_dense_from_prior_round(
    scenarios: list[dict], current_overall_fingerprint: Optional[str]
) -> Optional[tuple[dict, dict, dict]]:
    """只在"本轮内"找上一次 working_kb_retrieval_experiment_*.json，核实知识库+
    评估集指纹（snapshot_check.before_run.current_fingerprint）和本次完全一致、
    场景集合（query+relevant_pairs+member_sample_ids）逐条相等，才允许复用其
    Dense 候选——不是"样本数/场景数凑巧相等就认为一致"，是指纹级比对。

    和历史"旧 26 条 Evidence 结果不允许复用"是两件不同的事：那条规则针对的是
    knowledge_evidence_count=26 的旧结果，这里针对的是本轮同一个 37 条 Evidence
    working/ 快照下、仅仅换了 BM25 分词器的前一次运行——Dense 根本不读
    tokenizer，知识库和评估集都没变，复用是安全的，不是"为了形式统一"而是
    "避免对已经证明不受影响的变量重复花 13 秒模型加载 + 14 秒索引构建"。

    返回 (dense_candidates_by_key, dense_perf_dict, meta) 或 None（找不到/不一致）。
    """
    if not RESULTS_DIR.exists() or current_overall_fingerprint is None:
        return None
    candidates = sorted(RESULTS_DIR.glob(f"{KB_SOURCE_LABEL}_kb_retrieval_experiment_*.json"))
    if not candidates:
        return None
    latest = candidates[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    prior_fp = payload.get("snapshot_check", {}).get("before_run", {}).get("current_fingerprint")
    if prior_fp is None or prior_fp != current_overall_fingerprint:
        return None  # 知识库/评估集指纹不一致（或旧文件没存这个字段），不允许复用

    def key(sc: dict) -> tuple:
        return (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))

    prior_scenarios_by_key = {key(sc): sc for sc in payload.get("scenarios", [])}
    current_keys = {key(sc) for sc in scenarios}
    if set(prior_scenarios_by_key) != current_keys:
        return None  # 场景集合不完全一致，不允许复用
    for sc in scenarios:
        k = key(sc)
        if sorted(prior_scenarios_by_key[k]["member_sample_ids"]) != sorted(sc["member_sample_ids"]):
            return None  # 样本映射不一致，不允许复用

    dense_candidates_by_key = {}
    for sc in scenarios:
        k = key(sc)
        dense_candidates_by_key[k] = prior_scenarios_by_key[k]["candidates"]["dense"]

    dense_perf_dict = {
        "cold_start_and_model_init": payload["performance"]["cold_start_and_model_init"],
        "dense_query_embedding_and_retrieval": payload["performance"]["dense_query_embedding_and_retrieval"],
        "index_build_update_delete": {"dense": payload["performance"]["index_build_update_delete"]["dense"]},
    }
    meta = {"reused_from": str(latest), "reused_fingerprint": prior_fp}
    return dense_candidates_by_key, dense_perf_dict, meta


def run(rrf_k: int, skip_index_mutation: bool, tokenizer_force: Optional[str], force_rerun_dense: bool) -> dict:
    _assert_no_arbitration_leak()
    pre_snapshot_check = _verify_working_snapshot_unchanged("before_run")
    if pre_snapshot_check.get("checked") and pre_snapshot_check.get("changed"):
        raise SystemExit(
            "experiment_kb/working/ 的内容和 experiment_kb/snapshots/working_snapshot.json "
            "记录的指纹不一致（运行前检测到）——说明输入在本次实验之前被改动过，按规则中止，"
            f"不运行检索。差异详情: {json.dumps(pre_snapshot_check['diff'], ensure_ascii=False)[:2000]}"
        )

    evaluable = _load_evaluable_samples()
    scenarios = _build_scenarios(evaluable)
    knowledge_evidences = _load_working_knowledge_evidences()

    print(f"知识库：{len(knowledge_evidences)} 条 Evidence（experiment_kb/working/），"
          f"评估样本：{len(evaluable)} 条有效 / {len(scenarios)} 个独立场景")

    # ---- BM25 ----
    t_bm25_wall = time.perf_counter()
    bm25_candidates_by_key, bm25_perf, tokenizer_name = _run_bm25_channel(
        scenarios, knowledge_evidences, skip_index_mutation, tokenizer_force=tokenizer_force
    )
    bm25_wall_seconds = round(time.perf_counter() - t_bm25_wall, 3)
    print(f"BM25 完成：分词器={tokenizer_name}，总耗时 {bm25_wall_seconds}s")

    # ---- Dense：知识库/评估集指纹和本轮前一次运行完全一致时才允许复用，
    # 否则（含首次运行、--force-rerun-dense、指纹不一致）真实重跑 ----
    dense_reuse_meta = None
    current_fp = pre_snapshot_check.get("current_fingerprint") if pre_snapshot_check.get("checked") else None
    reused = None if force_rerun_dense else _try_reuse_dense_from_prior_round(scenarios, current_fp)
    t_dense_wall = time.perf_counter()
    if reused is not None:
        dense_candidates_by_key, dense_perf_dict, dense_reuse_meta = reused
        dense_wall_seconds = 0.0
        print(f"Dense 完成（复用本轮前一次运行的真实结果，指纹核对一致：{dense_reuse_meta['reused_from']}，"
              f"未重新调用 BGE-M3，没有'为了形式统一'无意义重复计算）")
    else:
        dense_candidates_by_key, dense_perf_dict = _run_dense_channel(
            scenarios, knowledge_evidences, skip_index_mutation
        )
        dense_wall_seconds = round(time.perf_counter() - t_dense_wall, 3)
        print(f"Dense 完成（真实重跑，未复用任何历史结果），总耗时 {dense_wall_seconds}s")

    # ---- RRF 融合 ----
    t_rrf = time.perf_counter()
    rrf_candidates_by_key: dict[tuple, list[dict]] = {}
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        rrf_candidates_by_key[key] = _rrf_fuse(
            dense_candidates_by_key[key], bm25_candidates_by_key[key], rrf_k=rrf_k, limit=CANDIDATE_K
        )
    rrf_fuse_seconds = round(time.perf_counter() - t_rrf, 3)

    # ---- 端到端混合检索耗时：serial vs parallel（query 级别，工程测量用）----
    def _serial_once(query: str) -> None:
        # 仅测量时间，不重新消费已经算好的候选——这里用轻量占位调用模拟"顺序执行
        # 两个通道"的墙钥时间，真实候选已经在上面产生，这一步不重算候选内容，
        # 只测两个通道各自单次调用再加 RRF 的串行耗时量级。
        pass

    hybrid_end_to_end = {
        "serial_total_seconds": round(
            dense_perf_dict["dense_query_embedding_and_retrieval"]["total_seconds"]
            + bm25_perf["total_seconds"]
            + rrf_fuse_seconds,
            3,
        ),
        "parallel_note": (
            "本脚本的 Dense/BM25 候选是分两个独立循环产生的（不是真正逐 query 用线程池"
            "并发跑两个通道），所以这里不伪造一个'并行耗时'数字——如果需要真实的 "
            "query 级并行耗时，需要在本机真实运行时改成 "
            "concurrent.futures.ThreadPoolExecutor 同时发起 Dense 检索和 BM25 检索，"
            "这里先如实标注未测量，不用 serial_total_seconds 近似代替。"
        ),
        "parallel_total_seconds": None,
    }

    # ---- 逐场景打分 ----
    strategies = {"dense": dense_candidates_by_key, "bm25": bm25_candidates_by_key, "rrf": rrf_candidates_by_key}
    scenario_records = []
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        relevant_pairs = set(key[1])
        record = {
            "query": sc["query"],
            "relevant_pairs": sc["relevant_pairs"],
            "member_sample_ids": sc["member_sample_ids"],
            "occurrence_count": sc["occurrence_count"],
            "candidates": {name: strategies[name][key] for name in strategies},
            "scores_by_strategy_and_k": {
                name: {
                    str(k): _score(relevant_pairs, [(d["source"], d["article"]) for d in strategies[name][key]], k)
                    for k in FINAL_TOP_KS
                }
                for name in strategies
            },
        }
        scenario_records.append(record)

    aggregate_scenario_level = {
        name: {str(k): _aggregate([r["scores_by_strategy_and_k"][name][str(k)] for r in scenario_records]) for k in FINAL_TOP_KS}
        for name in strategies
    }
    aggregate_sample_level = {}
    for name in strategies:
        aggregate_sample_level[name] = {}
        for k in FINAL_TOP_KS:
            rows = []
            for r in scenario_records:
                for _sid in r["member_sample_ids"]:
                    rows.append(r["scores_by_strategy_and_k"][name][str(k)])
            aggregate_sample_level[name][str(k)] = _aggregate(rows)

    top20_misses = _find_top20_misses(scenarios, dense_candidates_by_key, bm25_candidates_by_key)

    post_snapshot_check = _verify_working_snapshot_unchanged("after_run")

    performance = {
        "dense_query_embedding_and_retrieval": dense_perf_dict["dense_query_embedding_and_retrieval"],
        "bm25_tokenization_and_ranking": {k: v for k, v in bm25_perf.items() if k != "index_build_update_delete"},
        "rrf_fusion_overhead": {
            "total_seconds_for_all_scenarios": rrf_fuse_seconds,
            "distinct_scenario_count": len(scenarios),
            "mean_seconds_per_scenario": round(rrf_fuse_seconds / len(scenarios), 6) if scenarios else None,
        },
        "hybrid_end_to_end": hybrid_end_to_end,
        "index_build_update_delete": {
            "dense": dense_perf_dict["index_build_update_delete"]["dense"],
            "bm25": bm25_perf["index_build_update_delete"],
            "skipped": skip_index_mutation,
        },
        "cold_start_and_model_init": dense_perf_dict["cold_start_and_model_init"],
    }

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_base_source": f"experiment_kb/{KB_SOURCE_LABEL}/（不是生产 data/knowledge/）",
        "kb_source_label": KB_SOURCE_LABEL,
        "knowledge_evidence_count": len(knowledge_evidences),
        "candidate_k": CANDIDATE_K,
        "final_top_k_values": FINAL_TOP_KS,
        "rrf_k": rrf_k,
        "tokenizer_used": tokenizer_name,
        "total_evaluable_samples": len(evaluable),
        "distinct_scenario_count": len(scenarios),
        "dense_source_info": (
            {
                "mode": "reused_this_round",
                "reason": "知识库快照指纹和评估集指纹与本轮前一次运行逐一核对一致，"
                          "场景集合/样本映射逐条相等，Dense 不受 BM25 分词器切换影响，"
                          "复用真实结果，不重复调用 BGE-M3。",
                **dense_reuse_meta,
            }
            if dense_reuse_meta is not None
            else {
                "mode": "rerun_forced" if not force_rerun_dense else "rerun_forced_by_flag",
                "reason": (
                    "本轮规则：不允许把旧版 26 条 Evidence 上的 Dense 历史结果当作本轮基线，"
                    "experiment_kb/working/ 的知识库内容与历史结果不同，强制真实重跑。"
                    if not force_rerun_dense
                    else "命令行传了 --force-rerun-dense，即使指纹核对一致也强制重跑。"
                ),
            }
        ),
        "snapshot_check": {"before_run": pre_snapshot_check, "after_run": post_snapshot_check},
        "performance": performance,
        "aggregate_sample_level": aggregate_sample_level,
        "aggregate_scenario_level": aggregate_scenario_level,
        "top20_misses_never_recalled_by_either_channel": top20_misses,
        "scenarios": scenario_records,
        "caveats": [
            "标准答案（relevant 标签）尚未全部人工核验，本结果中的 Recall/MRR/nDCG 是"
            "基于当前（尚待完善人工核验的）标准答案标签算出的阶段性指标，不是最终真实 Recall。",
            "《劳动法》第三十六—四十五条来源版本仍标注为'尚待进一步核实'，"
            "《劳动合同法》第五十条确定性文本比对（difflib）仍未完成——这两点不阻塞本次工程实验，"
            "但本结果不能作为这两条法律文本本身已核验正确的证据。",
            "仲裁法第十—十六条全程未参与本次检索实验（未被本脚本读取，见启动断言），"
            "不在 Dense/BM25/RRF 任何候选列表中。",
            "本脚本尚未在真实环境中实际运行过——本次只完成静态代码检查和逻辑复核，"
            "任何数字性结果只有在你本机运行后才算'已实际验证'。",
        ],
    }
    return result


def _write_markdown_report(result: dict, output_path: Path) -> None:
    lines = []
    lines.append("# experiment_kb/working/ 检索策略实验报告（Dense / BM25 / RRF）\n\n")
    lines.append("> **阶段性结果声明**：标准答案尚未全部人工核验，以下指标不是最终真实 Recall。\n\n")
    lines.append(f"运行时间（UTC）：{result['run_at']}\n\n")
    lines.append(f"知识库来源：{result['knowledge_base_source']}，共 {result['knowledge_evidence_count']} 条 Evidence\n\n")
    lines.append(f"candidate_k={result['candidate_k']}  final_top_k={result['final_top_k_values']}  rrf_k={result['rrf_k']}  tokenizer={result['tokenizer_used']}\n\n")
    lines.append(f"样本/场景：{result['total_evaluable_samples']} 条有效样本，{result['distinct_scenario_count']} 个独立场景\n\n")
    lines.append(f"Dense 通道：{result['dense_source_info']['mode']}（{result['dense_source_info']['reason']}）\n\n")

    lines.append("## 质量指标（原始样本口径，188）\n\n| 策略 | K | Recall | MRR | nDCG |\n|---|---|---|---|---|\n")
    for strat in ["dense", "bm25", "rrf"]:
        for k in result["final_top_k_values"]:
            agg = result["aggregate_sample_level"][strat][str(k)]
            lines.append(f"| {strat} | {k} | {agg['recall']} | {agg['mrr']} | {agg['ndcg']} |\n")

    lines.append("\n## 质量指标（独立场景口径，等权重）\n\n| 策略 | K | Recall | MRR | nDCG |\n|---|---|---|---|---|\n")
    for strat in ["dense", "bm25", "rrf"]:
        for k in result["final_top_k_values"]:
            agg = result["aggregate_scenario_level"][strat][str(k)]
            lines.append(f"| {strat} | {k} | {agg['recall']} | {agg['mrr']} | {agg['ndcg']} |\n")

    lines.append(f"\n## Top-20 漏检（Dense 和 BM25 都没召回的相关法条）：{len(result['top20_misses_never_recalled_by_either_channel'])} 个场景\n\n")
    for m in result["top20_misses_never_recalled_by_either_channel"][:20]:
        lines.append(f"- query: {m['query'][:60]}... 漏检: {m['never_recalled_by_either_channel']}\n")

    lines.append("\n## 六项性能测量\n\n```json\n")
    lines.append(json.dumps(result["performance"], ensure_ascii=False, indent=2))
    lines.append("\n```\n")

    lines.append("\n## 限制声明\n\n")
    for c in result["caveats"]:
        lines.append(f"- {c}\n")

    output_path.write_text("".join(lines), encoding="utf-8")


def _run_dense_delete_test_only() -> dict:
    """独立于主实验流程的 Dense 索引"删除"耗时验证——不跑 BM25/RRF/质量指标，
    不影响统一计时实验的数字,专门用来确认修过 bug 之后的 delete 操作真的能跑通，
    并记录一次真实耗时。用完整的 build -> update -> delete 流程（和主流程的
    index_build_update_delete 逻辑一致），只是单独跑、单独存文件。
    """
    from rag import ChromaKnowledgeBase, KnowledgeLoader, LegalKnowledgeRetriever, build_embedder  # noqa: F401
    from rag.knowledge_loader import KnowledgeLoader as _KL

    _assert_no_arbitration_leak()
    knowledge_evidences = _load_working_knowledge_evidences()
    TMP_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    persist_dir = TMP_RUNTIME_DIR / f"dense_delete_test_{timestamp}"
    collection_name = f"experiment_kb_working_dense_delete_test_{timestamp}"
    _assert_isolated_from_official_db(persist_dir, collection_name)

    result = {"run_at": datetime.now(timezone.utc).isoformat(), "test": "dense_index_delete_standalone"}
    try:
        t0 = time.perf_counter()
        embedder = build_embedder()
        result["embedder_load_seconds"] = round(time.perf_counter() - t0, 3)

        t1 = time.perf_counter()
        kb = ChromaKnowledgeBase(embedder, persist_directory=persist_dir, collection_name=collection_name)
        loader = KnowledgeLoader(kb)
        loader.index(knowledge_evidences)
        result["initial_build_seconds"] = round(time.perf_counter() - t1, 3)
        result["initial_doc_count"] = kb.count()

        probe = knowledge_evidences[0]
        probe_id = _KL._evidence_id(probe)
        t_del = time.perf_counter()
        kb._store._collection.delete(ids=[probe_id])
        result["delete_one_evidence_seconds"] = round(time.perf_counter() - t_del, 3)
        result["doc_count_after_delete"] = kb.count()
        result["expected_doc_count_after_delete"] = result["initial_doc_count"] - 1
        result["delete_verified_correct"] = result["doc_count_after_delete"] == result["expected_doc_count_after_delete"]
        result["note"] = (
            "上一轮结果文件里的 Dense 删除耗时是 AttributeError 失败记录（'ChromaKnowledgeBase' "
            "object has no attribute 'collection'），脚本已修正为 kb._store._collection.delete(...)，"
            "这是修正后的独立验证结果，不影响任何已有结果文件。"
        )
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K)
    parser.add_argument("--skip-index-mutation", action="store_true")
    parser.add_argument(
        "--tokenizer", choices=["auto", "jieba", "char_bigram"], default="char_bigram",
        help="默认 char_bigram（本轮已确定的BM25主配置）。auto=自动探测（装了jieba用jieba，"
             "仅用于历史jieba对照，不作为主配置）；jieba=显式强制，没装jieba会直接报错退出。",
    )
    parser.add_argument("--force-rerun-dense", action="store_true", help="即使指纹核对一致也强制真实重跑 Dense。")
    parser.add_argument(
        "--dense-delete-test-only", action="store_true",
        help="只跑一次独立的 Dense 索引构建+删除验证，不跑完整实验、不影响已有结果文件。",
    )
    parser.add_argument(
        "--kb-source", choices=["working", "baseline"], default="working",
        help="working=experiment_kb/working/（37条Evidence，默认）；"
             "baseline=experiment_kb/baseline/（26条Evidence只读基线，用于和working公平对照）。"
             "两者用完全相同的代码路径、只是重新指向不同的知识库/评估集/快照记录文件，"
             "不是另外写一套检索逻辑。",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.kb_source == "baseline":
        global WORKING_DIR, WORKING_KNOWLEDGE_DIR, WORKING_SAMPLES_PATH, RECORDED_WORKING_SNAPSHOT_PATH, KB_SOURCE_LABEL
        WORKING_DIR = EXPERIMENT_DIR / "baseline"
        WORKING_KNOWLEDGE_DIR = WORKING_DIR / "data" / "knowledge"
        WORKING_SAMPLES_PATH = WORKING_DIR / "data" / "eval_samples" / "retrieval_eval_samples.json"
        RECORDED_WORKING_SNAPSHOT_PATH = EXPERIMENT_DIR / "snapshots" / "baseline_snapshot.json"
        KB_SOURCE_LABEL = "baseline"

    if args.dense_delete_test_only:
        test_result = _run_dense_delete_test_only()
        test_result["kb_source"] = KB_SOURCE_LABEL
        print(json.dumps(test_result, ensure_ascii=False, indent=2))
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = RESULTS_DIR / f"dense_delete_test_{KB_SOURCE_LABEL}_{ts}.json"
        out.write_text(json.dumps(test_result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n独立删除验证结果已写出: {out}")
        return

    tokenizer_force = None if args.tokenizer == "auto" else args.tokenizer
    result = run(args.rrf_k, args.skip_index_mutation, tokenizer_force, args.force_rerun_dense)

    print("=" * 78)
    print(f"知识库 Evidence 数={result['knowledge_evidence_count']}  tokenizer={result['tokenizer_used']}")
    for basis_name, basis in [("原始样本口径(188)", result["aggregate_sample_level"]), ("独立场景口径", result["aggregate_scenario_level"])]:
        print(f"--- {basis_name} ---")
        for strat in ["dense", "bm25", "rrf"]:
            for k in result["final_top_k_values"]:
                agg = basis[strat][str(k)]
                print(f"  {strat:6s} K={k:2d}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}")
    print(f"Top-20 两通道都漏检的场景数：{len(result['top20_misses_never_recalled_by_either_channel'])}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tok_tag = "jieba" if "jieba" in result["tokenizer_used"] else "char_bigram"
    output_path = args.output or (RESULTS_DIR / f"{KB_SOURCE_LABEL}_kb_retrieval_experiment_{timestamp}_{tok_tag}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写出: {output_path}")

    md_path = output_path.with_suffix(".md")
    _write_markdown_report(result, md_path)
    print(f"简短报告已写出: {md_path}")


if __name__ == "__main__":
    main()
