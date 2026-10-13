"""Dense / BM25 / Dense+BM25+RRF 检索策略对照实验。

【这个脚本在测什么、为什么测】
    上一轮 Dense Top-K(5/10/20) 实验发现：增大候选数量收益很小，少数场景
    （典型案例：“自愿放弃社保换 800 元现金补偿”）里，《劳动合同法》第十七条
    在 Top-20 里始终没有出现——怀疑是语义向量检索把这类“说法和法条原文用词
    差异较大，但语义上应该匹配”的 query 排到了候选池之外，不是“差一点没进
    前 5”的问题。本轮验证：
        1. BM25（词面匹配）能不能找回这些 Dense 漏检的法条——如果 query 里
           的关键词（“社会保险”“工资”“工作地点”）和法条原文直接重合，
           BM25 应该比向量检索更容易命中；
        2. Dense + BM25 用 RRF（Reciprocal Rank Fusion）融合排名之后，
           整体指标是不是比单一策略更好，还是只是“各有各的漏检，融合也救
           不回来”。

【输入 / 输出】
    输入：
        - data/eval_samples/retrieval_eval_samples.json
          （和上两轮完全相同的 188 条有效样本快照，不修改）
        - data/eval_samples/results/retrieval_topk_experiment_*.json
          （上一轮已经验证过的真实 Dense Top-20 结果，默认直接复用，见下方
          “Dense 通道怎么来的”）
        - data/knowledge/*.txt
          （和索引进 Chroma 时完全相同的法律文本，用同一个 KnowledgeLoader
          重新切分，只用来给 BM25 建索引，不重新写入任何数据库）
    输出：
        - data/eval_samples/results/retrieval_strategy_experiment_<时间戳>.json
          （三种策略在 188 条样本 / 47 个独立场景两套口径下的 Recall/MRR/nDCG，
          以及每个场景在三种策略下 candidate_k=20 的完整检索结果和排名）
        - data/eval_samples/results/retrieval_strategy_experiment_<时间戳>.md
          （给人看的简短实验报告：目标、控制变量、方法、真实结果、结论、限制）

【candidate_k 和 final_top_k 的区别——本脚本里最容易搞混的两个概念】
    candidate_k = 20：
        每个检索通道（Dense、BM25）各自内部检索/打分时取的候选深度。
        这是“通道能看到多少候选”，不是最终拿去算指标的数量。
        RRF 融合时，输入就是 Dense 和 BM25 各自的 candidate_k=20 候选排名；
        融合后的候选集合是两个通道候选的并集，大小可能等于、大于或小于 20
        （两个通道完全不重合时最多 40，完全重合时正好 20）。
    final_top_k ∈ {5, 10, 20}：
        最终参与 Recall/MRR/nDCG 计算时，从每个策略的排序结果里截断保留的
        条数。Dense/BM25 单策略时直接是 candidate_k=20 列表的前 final_top_k
        项；RRF 策略时是融合排序后的前 final_top_k 项。
    两者必须分开记录：下面的结果 JSON 里 candidate_k 和 final_top_k 是两个
    独立字段，不会混在一起。

【固定不变的东西 vs 本轮唯一改变的东西】
    固定：query 原文、标准相关法条标签（relevant）、knowledge 文本切分方式
         （KnowledgeLoader，chunk_size=500/chunk_overlap=50，和 Chroma 里
         实际索引时用的完全一样）、元数据（source/article/part）、评估公式
         （_score() 函数：按 (source, article) 匹配、宏平均、多标签按比例
         计分、nDCG 用二元相关性 + log2(i+2) 折损，和前两轮完全一致）。
    唯一改变的自变量：检索策略（Dense only / BM25 only / Dense+BM25+RRF）。

【Dense 通道怎么来的——复用还是重跑，由脚本自己核实后决定】
    优先复用上一轮已经真实跑过、已经核对过前缀一致性的 Dense Top-20 结果
    （`retrieval_topk_experiment_*.json`），不重新调用 BGE-M3/Chroma——
    但复用之前必须核实三件事，三件全部核实通过才允许用：
        a) 样本数/场景数一致：188 条有效样本、47 个独立 (query, 标签) 场景；
        b) 每个场景的 query 原文和 relevant 标签逐一字符串相等（不是“数量
           凑巧相等”这种弱校验）；
        c) **知识片段内容本身一致**：旧 dense 结果文件必须保存了知识片段的
           内容指纹（`knowledge_chunk_content_fingerprint`，按 (source,
           article, content) 算的哈希列表），和本轮 BM25 用的知识快照逐一
           比对完全相同，才算一致。

    **第 (c) 条是本脚本修正过的地方**：最早的版本只核实了 (a)(b)，隐含假设
    “样本/query/标签/模型参数都一样，知识库内容大概率也一样”——这个假设没有
    被验证过，`retrieval_topk_experiment_*.json` 这类旧结果文件里只存了一个
    `knowledge_base_doc_count`（纯数量），没有存实际内容，单凭数量相同不能
    排除“两边各自独立切分出的 26 个片段里有哪怕一个字不一样”的可能性。所以
    现在的规则是：**旧结果文件没有知识内容指纹字段，就一律视为"无法证明一致"
    ，不允许复用**，哪怕 (a)(b) 两条都通过。目前 `eval_retrieval_topk_experiment.py`
    产出的文件都没有这个字段，所以实际效果是：在那个脚本被更新到会保存内容
    指纹之前，这里会**一直真实重跑 Dense**，而不是复用。

    重跑路径不是"重新 glob 知识库目录、各自切分一次"，而是直接把 BM25 通道
    用的同一份 `knowledge_evidences`（已经切分好的 Evidence 列表，同一个
    Python 对象）传给 `KnowledgeLoader.index()` 写入临时 Chroma——这保证
    本轮 Dense 和 BM25 用的是字面意义上同一批知识内容，不是"两边分别跑了
    同样的算法，理论上应该一样"。

    重跑用真实 BGE-M3 + 临时 Chroma collection，复用
    eval_retrieval_topk_experiment.py 里验证过的同一套安全隔离逻辑。不管
    复用还是重跑，决定过程和原因都会写进输出 JSON 的 `timing.dense` 字段
    （`mode`="reused"/"rerun"，重跑时还会带上这次用的知识内容指纹）。

【BM25 通道：中文分词怎么处理】
    标准 BM25Okapi 公式（k1=1.5, b=0.75），自己实现，不引入 rank_bm25 之类
    的第三方包（避免给“能不能装上”这件事增加不确定性）。
    分词器优先级：
        1. 如果本机装了 jieba（`pip install jieba`），用 jieba 做词级分词
           ——这是更合理的中文分词方式。
        2. 没装 jieba 时，退化为**字符级 2-gram（bigram）**分词：把文本看成
           字符序列，相邻两个字符滑动组成一个词元（例如“社会保险”→
           “社会”“会保”“保险”）。这是纯标准库、确定性、不依赖任何词典的
           方案，刻意不是“整段话当一个词元”（那样 BM25 等于失效）。
        实际用的是哪一种，会打印在终端并写进结果 JSON 的 `tokenizer_used`
        字段——两次实验用不同分词器得到的 BM25 数字不可直接比较，必须看
        这个字段。
    query 和知识库文本用完全相同的分词函数，保证口径一致。

    BM25 用来建索引的知识库切片，是本次重新调用 KnowledgeLoader 对
    data/knowledge/*.txt 重新切分出来的——理论上应该和官方 Chroma 里实际
    存着的切片完全一样（因为用的是同一套 KnowledgeLoader/chunk_size/
    chunk_overlap/分隔符逻辑），但“理论上应该一样”不等于“已经核实一样”。
    脚本会在建完 BM25 索引后，**只读**打开官方 `data/chroma` collection，
    按内容确定性哈希 id（`KnowledgeLoader._evidence_id()`，覆盖 source/
    article/part/content 四个维度）比较两边的 id 集合是否完全相等——
    这一步同时核验了文本内容、元数据、片段数量三者是否一致，结果写进输出
    JSON 的 `knowledge_base_consistency` 字段。全程只调用 chromadb 的
    `collection.get()`，不涉及任何写入，不会碰官方库。

【Dense+BM25+RRF 通道：融合公式】
    对每个 query，分别拿 Dense 和 BM25 各自的 candidate_k=20 排名（第几名，
    不是分数本身——Dense 的距离分数和 BM25 的词频分数量纲完全不同，不能
    直接相加，RRF 存在的意义就是绕开这个问题）。融合分数：
        score(d) = Σ_channel  1 / (rrf_k + rank_channel(d))
    某个通道的 candidate_k=20 里没有出现这篇文档，这个通道对它的贡献记 0
    （不是惩罚、不是补一个很大的排名），rrf_k 固定为 60（经典 RRF 论文和
    Elasticsearch 默认值，这里不做参数搜索，固定记录在 `rrf_k` 字段里）。
    按融合分数从高到低重新排序，分数相同的按“两个通道排名之和”升序、再按
    Dense 排名升序做确定性的 tie-break。
    局限（必须明确）：RRF 只能重新排列两个通道各自已经召回的候选——如果
    Dense 和 BM25 的 candidate_k=20 都没有召回某个相关法条，RRF 无论怎么
    融合都不可能把它变出来，这不是融合算法的问题，是上游两个通道都没找到。

【运行】
    python scripts/eval_retrieval_strategy_experiment.py
    可选参数：
        --dense-results <path>   指定要复用的 Dense 实验结果文件
                                  （默认自动找 data/eval_samples/results/
                                  下最新的 retrieval_topk_experiment_*.json）
        --force-rerun-dense       即使核实通过，也强制真实重跑 Dense
        --rrf-k <int>             覆盖默认的 rrf_k=60（仍然只是固定一个值，
                                  不做参数搜索）
        --output <path>          覆盖默认的结果 JSON 输出路径

【安全】
    本脚本默认路径完全不连接 Chroma、不调用 BGE-M3（Dense 直接复用已有真实
    结果的 JSON 文件），自然不可能碰到正式 `data/chroma`。只有在一致性核实
    失败、必须重跑 Dense 时才会打开 Chroma——这条路径沿用
    eval_retrieval_topk_experiment.py 里验证过的
    `_assert_isolated_from_official_db()`：临时目录 + 独立 collection
    名（"retrieval_strategy_experiment_dense_rerun"），启动时断言不等于
    settings.CHROMA_DIR / settings.CHROMA_COLLECTION_NAME，用完即删。
    不修改 rag/retriever.py、rag/database.py、agents/review_agent.py、
    generate_query()，也不碰规则引擎。
"""

import argparse
import json
import math
import re
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402

SAMPLES_PATH = PROJECT_ROOT / "data" / "eval_samples" / "retrieval_eval_samples.json"
RESULTS_DIR = PROJECT_ROOT / "data" / "eval_samples" / "results"
CANDIDATE_K = 20
FINAL_TOP_KS = [5, 10, 20]
DEFAULT_RRF_K = 60
DENSE_RERUN_COLLECTION_NAME = "retrieval_strategy_experiment_dense_rerun"


# ======================================================================
# 0. 评估样本 / 场景加载（和前两轮完全相同的分组逻辑，不用 Top-5 作为分组键）
# ======================================================================

def _load_evaluable_samples() -> list[dict]:
    if not SAMPLES_PATH.exists():
        raise SystemExit(f"找不到 {SAMPLES_PATH}，请先运行 build_retrieval_eval_samples.py")
    payload = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    return [s for s in payload["samples"] if s["evaluable"]]


def _label_key(sample: dict) -> tuple:
    return tuple(sorted((r["source"], r["article"]) for r in sample["relevant"]))


def _build_scenarios(evaluable: list[dict]) -> list[dict]:
    """按 (query, 标签) 分组，返回 [{query, relevant_pairs, member_sample_ids, occurrence_count}]。"""
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
# 1. Dense 通道：复用已验证的真实结果，或在核实失败时真实重跑
# ======================================================================

def _find_latest_dense_results() -> Optional[Path]:
    candidates = sorted(RESULTS_DIR.glob("retrieval_topk_experiment_*.json"))
    return candidates[-1] if candidates else None


def _knowledge_content_fingerprint(evidences: list) -> list[str]:
    """知识片段的内容指纹：按 (source, article, content) 算哈希、排序后的列表。
    和 `_evidence_id()` 不同——不受 `part` 字段哈希算法版本变化的影响，只认
    "文本内容+来源+条号"本身，专门用来回答"两次用的知识片段内容是否完全一样"
    这个问题（而不是"两次算出来的内部 id 是否一样"）。
    """
    import hashlib

    fp = [
        hashlib.sha256(f"{e.source}\x00{e.article or ''}\x00{e.content}".encode("utf-8")).hexdigest()
        for e in evidences
    ]
    return sorted(fp)


def _verify_dense_results_match(dense_payload: dict, scenarios: list[dict], current_fingerprint: list[str]) -> list[str]:
    """核实 dense_payload 和当前样本快照/知识快照是否一致，返回差异说明列表（空=一致）。

    知识内容这一条是硬性要求：旧的 dense 结果文件如果没有保存
    `knowledge_chunk_content_fingerprint` 字段（目前 eval_retrieval_topk_experiment.py
    产出的文件就是这种情况——它只存了 `knowledge_base_doc_count` 这个数量，没有存
    实际内容指纹），就**不能**仅凭样本数/场景数/query/标签/模型参数一致判断"知识内容
    也一致"——这是本次用户明确要求纠正的地方：旧的判断方式只验证了检索输入
    (query/标签)，没有验证检索的对象（知识库切片本身），两者独立，不能互相替代。
    """
    problems: list[str] = []
    if dense_payload.get("total_evaluable_samples") != sum(s["occurrence_count"] for s in scenarios):
        problems.append(
            f"有效样本总数不一致：dense 结果={dense_payload.get('total_evaluable_samples')}，"
            f"当前快照={sum(s['occurrence_count'] for s in scenarios)}"
        )
    if dense_payload.get("distinct_scenario_count") != len(scenarios):
        problems.append(
            f"独立场景数不一致：dense 结果={dense_payload.get('distinct_scenario_count')}，"
            f"当前快照={len(scenarios)}"
        )
    if dense_payload.get("model_name") != settings.EMBEDDING_MODEL_NAME:
        problems.append(
            f"模型配置不一致：dense 结果用的是 {dense_payload.get('model_name')}，"
            f"当前 settings.EMBEDDING_MODEL_NAME={settings.EMBEDDING_MODEL_NAME}"
        )
    dense_scenarios_by_key = {
        (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc
        for sc in dense_payload.get("scenarios", [])
    }
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        if key not in dense_scenarios_by_key:
            problems.append(f"当前场景在 dense 结果里找不到完全匹配的 (query, 标签)：{sc['query'][:40]}...")

    old_fingerprint = dense_payload.get("knowledge_chunk_content_fingerprint")
    if old_fingerprint is None:
        problems.append(
            "旧 dense 结果文件没有保存知识片段内容指纹（knowledge_chunk_content_fingerprint），"
            "只凭样本/query/标签/模型参数一致不能证明两次用的知识库切片内容也一致——"
            "按规则不允许复用，必须重新真实运行 Dense。"
        )
    elif sorted(old_fingerprint) != current_fingerprint:
        problems.append(
            f"知识片段内容指纹不一致：旧 dense 结果={len(old_fingerprint)} 个片段，"
            f"本次 BM25 用的知识快照={len(current_fingerprint)} 个片段，内容不完全相同。"
        )
    return problems


def _dense_candidates_from_reused_results(dense_payload: dict, scenarios: list[dict]) -> dict[tuple, list[dict]]:
    """从已验证一致的 dense_payload 里，取出每个场景 candidate_k=20 的 Dense 候选列表。"""
    dense_scenarios_by_key = {
        (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"]))): sc
        for sc in dense_payload["scenarios"]
    }
    out = {}
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        dense_sc = dense_scenarios_by_key[key]
        # dense 实验的 retrieved["20"] 就是 candidate_k=20 的真实结果，直接拿来用。
        out[key] = [
            {"source": d["source"], "article": d["article"], "score": d.get("score")}
            for d in dense_sc["retrieved"]["20"]
        ]
    return out


def _rerun_dense_for_real(scenarios: list[dict], reason: str, knowledge_evidences: list) -> tuple[dict[tuple, list[dict]], dict]:
    """核实失败（或知识内容无法证明一致）时的兜底路径：真实调用 BGE-M3 + 临时
    Chroma，重新拿 candidate_k=20。

    关键点：这里直接把 BM25 通道用的同一份 `knowledge_evidences`（已经切分好的
    Evidence 列表）喂给 `loader.index(evidences)` 写入临时 Chroma，**不是**
    重新 glob 知识库目录、重新调用 `load_and_index_file()` 各自独立切分一次。
    这保证本轮 Dense 和 BM25 用的是同一个 Python 对象列表、字面意义上的同一批
    知识片段，不存在"两边各自切分、理论上应该一样但没验证"的问题。
    """
    from rag import ChromaKnowledgeBase, KnowledgeLoader, LegalKnowledgeRetriever, build_embedder

    persist_dir = Path(tempfile.mkdtemp(prefix="eval_strategy_dense_rerun_"))
    official_dir = settings.CHROMA_DIR.resolve()
    temp_dir = persist_dir.resolve()
    assert temp_dir != official_dir, f"临时目录和正式目录撞了：{temp_dir}"
    assert not str(temp_dir).startswith(str(official_dir)), f"临时目录在正式目录内部：{temp_dir}"
    assert DENSE_RERUN_COLLECTION_NAME != settings.CHROMA_COLLECTION_NAME, "临时 collection 名和正式名相同"

    timing = {}
    try:
        t0 = time.perf_counter()
        embedder = build_embedder()
        timing["embedder_load_seconds"] = round(time.perf_counter() - t0, 3)

        t1 = time.perf_counter()
        kb = ChromaKnowledgeBase(embedder, persist_directory=persist_dir, collection_name=DENSE_RERUN_COLLECTION_NAME)
        loader = KnowledgeLoader(kb)
        loader.index(knowledge_evidences)  # 和 BM25 用的是同一份 evidences，不重新切分
        timing["knowledge_base_build_seconds"] = round(time.perf_counter() - t1, 3)
        timing["knowledge_base_doc_count"] = kb.count()

        retriever = LegalKnowledgeRetriever(kb)
        out = {}
        t2 = time.perf_counter()
        for sc in scenarios:
            key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
            retrieved = retriever.search_legal_knowledge(sc["query"], k=CANDIDATE_K)
            out[key] = [{"source": e.source, "article": e.article, "score": e.metadata.get("score")} for e in retrieved]
        timing["retrieval_total_seconds"] = round(time.perf_counter() - t2, 3)
        timing["rerun_reason"] = reason
        return out, timing
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)


# ======================================================================
# 2. BM25 通道：自实现 BM25Okapi + jieba/字符 bigram 分词
# ======================================================================

def _get_tokenizer() -> tuple[str, Callable[[str], list[str]]]:
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


def _load_knowledge_evidences() -> list:
    """用和 Chroma 索引时完全相同的 KnowledgeLoader 重新切分知识库文本。
    不写入任何数据库，纯内存操作。返回未合并的原始 Evidence 列表（和写入
    官方 Chroma 时`index()`接收到的输入逐条一致），供下面两处分别使用：
    `_load_knowledge_documents_for_bm25()`按(source,article)合并成 BM25 的
    检索单位；`_verify_knowledge_base_against_official_db()`逐条核对官方库。
    """
    from rag.knowledge_loader import KnowledgeLoader

    loader = KnowledgeLoader.__new__(KnowledgeLoader)  # 只用它的切分逻辑，不需要真的连 Chroma
    loader.chunk_size = settings.KNOWLEDGE_CHUNK_SIZE
    loader.chunk_overlap = settings.KNOWLEDGE_CHUNK_OVERLAP
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from rag.knowledge_loader import _SEPARATORS

    loader._splitter = RecursiveCharacterTextSplitter(
        chunk_size=loader.chunk_size,
        chunk_overlap=loader.chunk_overlap,
        separators=_SEPARATORS,
        is_separator_regex=True,
        keep_separator="end",
        strip_whitespace=True,
    )
    return loader.load_directory(settings.KNOWLEDGE_DIR)


def _load_knowledge_documents_for_bm25(evidences: list) -> list[dict]:
    """按 (source, article) 合并 part（如果某条法条被二次切分成多个 part，
    拼回一份整条文本），得到和 Dense 结果同一粒度（按条）的 BM25 文档集合。
    """
    merged: dict[tuple, list[str]] = {}
    for e in evidences:
        key = (e.source, e.article)
        merged.setdefault(key, []).append(e.content)

    docs = []
    for (source, article), parts in merged.items():
        docs.append({"source": source, "article": article, "text": "".join(parts)})
    return docs


def _verify_knowledge_base_against_official_db(evidences: list) -> dict:
    """核对本次 BM25 用来建索引的知识库切片，和**正式环境真正存在 Chroma 里**
    的切片是否逐条一致——不是“再跑一遍同样的切分逻辑就认为一致”，而是直接
    只读打开官方 collection 取出真实存着的 (id, content, metadata)，和本次
    重新切分出来的 Evidence 做两层比较：

        1. **主比较：按 (source, article, content) 内容本身比较**（用
           Counter 做多重集合比较，不要求顺序一致）——这是“内容、关键元数据、
           数量是否一致”这个问题最直接、最不会被其他因素干扰的答案。
        2. **辅助比较：按 `KnowledgeLoader._evidence_id()` 算出的确定性哈希 id
           比较**——理论上和主比较应该给出同一个结论，但如果官方库是在
           `_evidence_id()`的哈希算法本身发生变更（例如 2026-10-10 那次把
           `part` 字段纳入哈希的修复）**之前**写入的，id 的字符串就会和用
           当前代码重新算出来的不一样，即使内容/元数据完全没变——这种情况下
           id 比较会误报“不一致”，所以不能只看 id，必须以内容比较为准，
           id 比较只作为“是否怀疑哈希算法版本漂移”的旁证，写在
           `id_mismatch_likely_due_to_hash_scheme_change` 字段里。

    全程只调用 chromadb 的只读 `collection.get()`，不调用 add/upsert/delete，
    不建立新 collection、不传 embedding_function（get() 不需要向量化），
    绝对不会修改、清空或重建正式 `data/chroma`。
    """
    from rag.knowledge_loader import KnowledgeLoader

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(settings.CHROMA_DIR))
        collection = client.get_collection(name=settings.CHROMA_COLLECTION_NAME)
        raw = collection.get(include=["metadatas", "documents"])
    except Exception as exc:  # noqa: BLE001 - 核验失败要如实报告原因，不能让整个实验崩掉
        return {
            "checked": False,
            "reason": f"无法只读连接官方 Chroma collection 做核验: {exc!r}",
            "content_match_exactly": None,
            "ids_match_exactly": None,
            "problems": [],
        }

    from collections import Counter

    official_ids = set(raw["ids"])
    official_content_tuples = [
        (m.get("source"), m.get("article"), doc) for m, doc in zip(raw["metadatas"], raw["documents"])
    ]
    fresh_content_tuples = [(e.source, e.article, e.content) for e in evidences]

    official_content_counter = Counter(official_content_tuples)
    fresh_content_counter = Counter(fresh_content_tuples)
    content_match_exactly = official_content_counter == fresh_content_counter

    fresh_ids = {KnowledgeLoader._evidence_id(e) for e in evidences}
    ids_match_exactly = official_ids == fresh_ids

    problems = []
    if len(official_content_tuples) != len(fresh_content_tuples):
        problems.append(f"片段数量不一致：官方库={len(official_content_tuples)}，本次重新切分={len(fresh_content_tuples)}")
    if not content_match_exactly:
        missing_content = list((official_content_counter - fresh_content_counter).elements())
        extra_content = list((fresh_content_counter - official_content_counter).elements())
        if missing_content:
            problems.append(
                f"按内容比较：官方库里有 {len(missing_content)} 个片段，本次重新切分的文本里找不到完全相同的 (source,article,content)，"
                f"例如: {missing_content[0]}"
            )
        if extra_content:
            problems.append(
                f"按内容比较：本次重新切分多出 {len(extra_content)} 个官方库里没有的片段，例如: {extra_content[0]}"
            )

    id_mismatch_likely_due_to_hash_scheme_change = (
        content_match_exactly and not ids_match_exactly
    )
    if id_mismatch_likely_due_to_hash_scheme_change:
        problems.append(
            "内容完全一致，但 _evidence_id() 算出的哈希 id 全部不同——"
            "大概率是官方库写入时用的是旧版 _evidence_id()（2026-10-10 加入 part 字段"
            "之前的 3 段哈希），而不是内容真的变了；这不影响 BM25/Dense/RRF 的检索正确性"
            "（三个通道都按 (source, article) 匹配，不依赖这个内部 id），只是 id 本身的"
            "哈希算法版本和当前代码不一致，供参考。"
        )

    return {
        "checked": True,
        "official_doc_count": len(official_content_tuples),
        "freshly_split_doc_count": len(fresh_content_tuples),
        "content_match_exactly": content_match_exactly,
        "ids_match_exactly": ids_match_exactly,
        "id_mismatch_likely_due_to_hash_scheme_change": id_mismatch_likely_due_to_hash_scheme_change,
        "problems": problems,
    }


class _BM25Index:
    """标准 BM25Okapi（k1=1.5, b=0.75），纯标准库实现。"""

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
        order = sorted(range(self.N), key=lambda i: (-scores[i], i))  # 确定性 tie-break：原始顺序
        top = order[:k]
        return [
            {"source": self.docs[i]["source"], "article": self.docs[i]["article"], "score": round(scores[i], 6)}
            for i in top
        ]


# ======================================================================
# 3. RRF 融合
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
# 4. 评估公式（和前两轮完全一致，不新发明一套）
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


# ======================================================================
# 5. 主流程
# ======================================================================

def run(dense_results_path: Optional[Path], force_rerun_dense: bool, rrf_k: int) -> dict:
    evaluable = _load_evaluable_samples()
    scenarios = _build_scenarios(evaluable)

    # ---- 先把本轮固定要用的知识快照切好（BM25 和"万一要重跑的 Dense"共用同一份）----
    knowledge_evidences = _load_knowledge_evidences()
    current_fingerprint = _knowledge_content_fingerprint(knowledge_evidences)

    # 知识库一致性核验：这份知识快照是否和官方 Chroma 里实际存着的切片
    # （内容、source/article/part 元数据、数量）逐条一致——不是假定一致，
    # 是直接只读查官方库做比对，见 _verify_knowledge_base_against_official_db()。
    kb_consistency = _verify_knowledge_base_against_official_db(knowledge_evidences)
    if kb_consistency["checked"]:
        if kb_consistency["content_match_exactly"]:
            print(f"知识库一致性核验通过（按内容比较）：BM25 切片与官方 Chroma 里的 {kb_consistency['official_doc_count']} 个片段内容+元数据+数量逐条一致。")
            if kb_consistency["id_mismatch_likely_due_to_hash_scheme_change"]:
                print("  注意：内部 id 哈希不一致，大概率是官方库写入时的 _evidence_id() 版本更旧（见该字段的说明），不影响检索正确性。")
        else:
            print("知识库一致性核验未通过（按内容比较），发现差异：")
            for p in kb_consistency["problems"]:
                print("  -", p)
    else:
        print(f"知识库一致性核验未能执行：{kb_consistency['reason']}")

    # ---- BM25 通道：建索引（用上面同一份 knowledge_evidences）----
    t_bm25 = time.perf_counter()
    bm25_docs = _load_knowledge_documents_for_bm25(knowledge_evidences)
    tokenizer_name, tokenize = _get_tokenizer()
    bm25_index = _BM25Index(bm25_docs, tokenize)
    bm25_build_seconds = round(time.perf_counter() - t_bm25, 3)
    print(f"BM25 索引建好：{len(bm25_docs)} 篇文档，分词器={tokenizer_name}，耗时 {bm25_build_seconds}s")

    # ---- Dense 通道：核实"知识内容是否可证明一致" -> 复用或重跑 ----
    # 本轮修正（用户指出）：旧的核实只比较了样本/query/标签/模型参数，没有比较
    # Dense 实验当时实际索引的知识片段内容本身——旧 dense 结果文件没有保存这个
    # 内容指纹，所以不能证明一致，必须重新真实跑一次 Dense，并且直接复用上面
    # 已经核验过的同一份 knowledge_evidences，保证 Dense 和 BM25 用的是同一批
    # 知识内容（不是"分别切分、理论上一样"）。
    dense_source_info: dict = {}
    if dense_results_path is None:
        dense_results_path = _find_latest_dense_results()

    dense_candidates_by_key: dict[tuple, list[dict]] = {}
    if dense_results_path is not None and dense_results_path.exists() and not force_rerun_dense:
        dense_payload = json.loads(dense_results_path.read_text(encoding="utf-8"))
        problems = _verify_dense_results_match(dense_payload, scenarios, current_fingerprint)
        if not problems:
            dense_candidates_by_key = _dense_candidates_from_reused_results(dense_payload, scenarios)
            dense_source_info = {
                "mode": "reused",
                "reused_from": str(dense_results_path),
                "verified_consistent": True,
                "verification_problems": [],
                "knowledge_content_verified": True,
            }
            print(f"Dense 通道：核实通过（含知识内容指纹比对），复用 {dense_results_path}")
        else:
            print("Dense 结果核实未通过（样本/标签一致不等于知识内容一致），改为真实重跑：")
            for p in problems:
                print("  -", p)
            dense_candidates_by_key, rerun_timing = _rerun_dense_for_real(
                scenarios, reason="知识内容无法证明一致: " + "; ".join(problems), knowledge_evidences=knowledge_evidences
            )
            dense_source_info = {
                "mode": "rerun",
                "reason": "知识内容无法证明一致，按规则不允许复用",
                "verification_problems": problems,
                "knowledge_content_shared_with_bm25": True,
                "knowledge_chunk_content_fingerprint": current_fingerprint,
                "rerun_timing": rerun_timing,
            }
    else:
        reason = "未找到可复用的 dense 结果文件" if dense_results_path is None else "--force-rerun-dense 指定强制重跑"
        print(f"真实重跑 Dense（原因：{reason}）")
        dense_candidates_by_key, rerun_timing = _rerun_dense_for_real(
            scenarios, reason=reason, knowledge_evidences=knowledge_evidences
        )
        dense_source_info = {
            "mode": "rerun",
            "reason": reason,
            "knowledge_content_shared_with_bm25": True,
            "knowledge_chunk_content_fingerprint": current_fingerprint,
            "rerun_timing": rerun_timing,
        }

    bm25_candidates_by_key: dict[tuple, list[dict]] = {}
    bm25_query_seconds = []
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        t1 = time.perf_counter()
        bm25_candidates_by_key[key] = bm25_index.search(sc["query"], CANDIDATE_K)
        bm25_query_seconds.append(time.perf_counter() - t1)

    # ---- RRF 融合 ----
    t2 = time.perf_counter()
    rrf_candidates_by_key: dict[tuple, list[dict]] = {}
    for sc in scenarios:
        key = (sc["query"], tuple(sorted(tuple(p) for p in sc["relevant_pairs"])))
        rrf_candidates_by_key[key] = _rrf_fuse(
            dense_candidates_by_key[key], bm25_candidates_by_key[key], rrf_k=rrf_k, limit=CANDIDATE_K
        )
    rrf_fuse_seconds = round(time.perf_counter() - t2, 3)

    # ---- 逐场景打分（三种策略 x final_top_k in {5,10,20}） ----
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
            "candidates": {
                name: strategies[name][key] for name in strategies
            },
            "scores_by_strategy_and_k": {
                name: {
                    str(k): _score(
                        relevant_pairs,
                        [(d["source"], d["article"]) for d in strategies[name][key]],
                        k,
                    )
                    for k in FINAL_TOP_KS
                }
                for name in strategies
            },
        }
        scenario_records.append(record)

    # ---- 两套口径汇总 ----
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

    timing = {
        "dense": dense_source_info,
        "bm25_index_build_seconds": bm25_build_seconds,
        "bm25_distinct_query_count": len(bm25_query_seconds),
        "bm25_total_query_seconds": round(sum(bm25_query_seconds), 3),
        "bm25_mean_query_seconds": round(statistics.mean(bm25_query_seconds), 4) if bm25_query_seconds else None,
        "rrf_fuse_seconds_for_all_47_scenarios": rrf_fuse_seconds,
        "note": (
            "bm25/rrf 的耗时是对 47 个【不同 query】分别计时；dense 这一项如果是 "
            "mode=reused，表示这次没有产生新的检索耗时，直接复用了上一轮真实计时过的结果，"
            "不能把 bm25/rrf 的耗时和 dense 的旧计时直接相加当成'这次实验的总耗时'——"
            "三者的计时口径和产生时间都不同。"
        ),
    }

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "candidate_k": CANDIDATE_K,
        "final_top_k_values": FINAL_TOP_KS,
        "rrf_k": rrf_k,
        "tokenizer_used": tokenizer_name,
        "total_evaluable_samples": len(evaluable),
        "distinct_scenario_count": len(scenarios),
        "knowledge_base_consistency": kb_consistency,
        "timing": timing,
        "aggregate_sample_level": aggregate_sample_level,
        "aggregate_scenario_level": aggregate_scenario_level,
        "scenarios": scenario_records,
    }
    return result


def _print_summary(result: dict) -> None:
    print("=" * 78)
    print(f"candidate_k={result['candidate_k']}  final_top_k={result['final_top_k_values']}  rrf_k={result['rrf_k']}")
    print(f"tokenizer_used={result['tokenizer_used']}")
    print(f"样本数={result['total_evaluable_samples']}  独立场景数={result['distinct_scenario_count']}")
    print(f"dense 通道来源: {result['timing']['dense']}")
    print(f"知识库一致性核验: {result['knowledge_base_consistency']}")
    for basis_name, basis in [("原始样本口径(188)", result["aggregate_sample_level"]), ("独立场景口径(47)", result["aggregate_scenario_level"])]:
        print(f"\n--- {basis_name} ---")
        for strat in ["dense", "bm25", "rrf"]:
            for k in result["final_top_k_values"]:
                agg = basis[strat][str(k)]
                print(f"  {strat:6s} K={k:2d}: Recall={agg['recall']}  MRR={agg['mrr']}  nDCG={agg['ndcg']}")


def _write_markdown_report(result: dict, output_path: Path) -> None:
    lines = []
    lines.append("# Dense / BM25 / Dense+BM25+RRF 检索策略对照实验报告\n")
    lines.append(f"运行时间（UTC）：{result['run_at']}\n")
    lines.append("## 目标\n")
    lines.append(
        "验证 Dense 向量检索漏掉的相关法条（典型案例：'自愿放弃社保换现金补偿'场景下"
        "《劳动合同法》第十七条在 Top-20 内完全不出现）能否被 BM25 词面匹配找回，"
        "以及 Dense+BM25 用 RRF 融合后整体指标是否更好。\n"
    )
    lines.append("## 控制变量\n")
    lines.append(
        f"- candidate_k={result['candidate_k']}（每个通道的候选深度），"
        f"final_top_k={result['final_top_k_values']}（评估截断深度），"
        f"rrf_k={result['rrf_k']}（固定值，本轮不做参数搜索）\n"
        f"- 分词器：{result['tokenizer_used']}\n"
        f"- 样本/场景：{result['total_evaluable_samples']} 条有效样本，"
        f"{result['distinct_scenario_count']} 个独立 (query, 标签) 场景\n"
        f"- Dense 通道来源：{result['timing']['dense'].get('mode')}"
        + (f"（复用 {result['timing']['dense'].get('reused_from')}）" if result['timing']['dense'].get('mode') == 'reused' else f"（原因：{result['timing']['dense'].get('reason')}）")
        + "\n"
        + f"- 知识库一致性核验（BM25 用的切片 vs 官方 Chroma 实际存着的切片）：{result['knowledge_base_consistency']}\n"
    )
    lines.append("## 真实结果（原始样本口径，188 条）\n")
    lines.append("| 策略 | K | Recall | MRR | nDCG |\n|---|---|---|---|---|\n")
    for strat in ["dense", "bm25", "rrf"]:
        for k in result["final_top_k_values"]:
            agg = result["aggregate_sample_level"][strat][str(k)]
            lines.append(f"| {strat} | {k} | {agg['recall']} | {agg['mrr']} | {agg['ndcg']} |\n")
    lines.append("\n## 真实结果（独立场景口径，47 个场景，等权重）\n")
    lines.append("| 策略 | K | Recall | MRR | nDCG |\n|---|---|---|---|---|\n")
    for strat in ["dense", "bm25", "rrf"]:
        for k in result["final_top_k_values"]:
            agg = result["aggregate_scenario_level"][strat][str(k)]
            lines.append(f"| {strat} | {k} | {agg['recall']} | {agg['mrr']} | {agg['ndcg']} |\n")
    lines.append(
        "\n## 结论与限制\n\n"
        "详见对话中的文字分析（重点失败样本的逐条法条排名、哪个通道找回了什么、"
        "RRF 是否只是在重排已召回的候选）。本报告只保留可复现的真实数字，"
        "结论性文字以实际跑出来的数据为准，不在这里重复粘贴。\n"
    )
    output_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dense-results", type=Path, default=None)
    parser.add_argument("--force-rerun-dense", action="store_true")
    parser.add_argument("--rrf-k", type=int, default=DEFAULT_RRF_K)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = run(args.dense_results, args.force_rerun_dense, args.rrf_k)
    _print_summary(result)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or (RESULTS_DIR / f"retrieval_strategy_experiment_{timestamp}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已写出: {output_path}")

    md_path = output_path.with_suffix(".md")
    _write_markdown_report(result, md_path)
    print(f"简短报告已写出: {md_path}")


if __name__ == "__main__":
    main()
