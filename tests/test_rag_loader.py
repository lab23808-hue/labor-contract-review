"""rag/knowledge_loader.py（KnowledgeLoader）的单元测试。运行：在项目根目录执行 `pytest`。"""

import pytest

from retrieval import DenseBackend
from retrieval.knowledge_loader import KnowledgeLoader
from core import Evidence
from tests._rag_fakes import FakeEmbeddings

SAMPLE_LAW = (
    "第十七条 劳动合同应当具备以下条款：劳动合同期限、工作内容、劳动报酬。\n"
    "第十九条 劳动合同期限三个月以上不满一年的，试用期不得超过一个月。\n"
    "第二十条 劳动者在试用期的工资不得低于本单位相同岗位最低档工资的百分之八十。\n"
)


def make_loader(tmp_path, **kwargs) -> KnowledgeLoader:
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    return KnowledgeLoader(kb, **kwargs)


# ---------- 切分（纯函数） ----------

def test_split_text_produces_one_evidence_per_article(tmp_path):
    evidences = make_loader(tmp_path).split_text(SAMPLE_LAW, source="劳动合同法")

    assert [e.article for e in evidences] == ["第十七条", "第十九条", "第二十条"]
    assert all(e.source == "劳动合同法" for e in evidences)
    assert evidences[0].content == (
        "第十七条 劳动合同应当具备以下条款：劳动合同期限、工作内容、劳动报酬。"
    )


def test_split_text_without_articles_keeps_whole_text():
    loader = KnowledgeLoader(DenseBackend(FakeEmbeddings(), persist_directory="/tmp/unused_kb_dir_x"))
    evidences = loader.split_text("这是一段没有条号的说明性文字。", source="说明")

    assert len(evidences) == 1
    assert evidences[0].article is None
    assert evidences[0].content == "这是一段没有条号的说明性文字。"


def test_oversized_article_is_split_with_part_metadata(tmp_path):
    long_article = "第一条 " + "违反规章制度的，用人单位可以解除劳动合同。" * 20
    loader = make_loader(tmp_path, chunk_size=100, chunk_overlap=20)

    evidences = loader.split_text(long_article, source="法A")

    assert len(evidences) > 1
    assert all(e.article == "第一条" for e in evidences)
    assert all(len(e.content) <= 100 for e in evidences)
    assert [e.metadata["part"] for e in evidences] == list(range(1, len(evidences) + 1))
    assert all(e.metadata["parts"] == len(evidences) for e in evidences)


def test_short_articles_are_not_split(tmp_path):
    evidences = make_loader(tmp_path, chunk_size=500).split_text(SAMPLE_LAW, source="劳动合同法")
    assert all(e.metadata == {} for e in evidences)


def test_reference_to_another_article_is_not_a_heading():
    loader = KnowledgeLoader(DenseBackend(FakeEmbeddings(), persist_directory="/tmp/unused_kb_dir_y"))
    text = "第一条 违约处理\n依照\n第三十九条的规定处理。\n第二条 其他\n无。"

    evidences = loader.split_text(text, source="法A")

    assert [e.article for e in evidences] == ["第一条", "第二条"]


def test_invalid_chunk_parameters_rejected(tmp_path):
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    with pytest.raises(ValueError):
        KnowledgeLoader(kb, chunk_size=0)
    with pytest.raises(ValueError):
        KnowledgeLoader(kb, chunk_size=100, chunk_overlap=100)


# ---------- 读文件 / 目录 ----------

def test_load_file_uses_filename_as_default_source(tmp_path):
    law_file = tmp_path / "劳动合同法.txt"
    law_file.write_text(SAMPLE_LAW, encoding="utf-8")

    evidences = make_loader(tmp_path).load_file(law_file)

    assert all(e.source == "劳动合同法" for e in evidences)


def test_load_file_accepts_explicit_source(tmp_path):
    law_file = tmp_path / "raw.txt"
    law_file.write_text(SAMPLE_LAW, encoding="utf-8")

    evidences = make_loader(tmp_path).load_file(law_file, source="劳动合同法（2018修正）")

    assert all(e.source == "劳动合同法（2018修正）" for e in evidences)


def test_load_directory_reads_all_txt_files_with_own_source(tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "法A.txt").write_text("第一条 甲内容。", encoding="utf-8")
    (knowledge_dir / "法B.txt").write_text("第一条 乙内容。", encoding="utf-8")
    (knowledge_dir / "说明.md").write_text("不是 txt，应被忽略", encoding="utf-8")

    evidences = make_loader(tmp_path).load_directory(knowledge_dir)

    assert {e.source for e in evidences} == {"法A", "法B"}
    assert len(evidences) == 2


# ---------- 写入数据库（切分 + 入库整合）----------

def test_load_and_index_file_writes_to_knowledge_base(tmp_path):
    law_file = tmp_path / "劳动合同法.txt"
    law_file.write_text(SAMPLE_LAW, encoding="utf-8")
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    loader = KnowledgeLoader(kb)

    evidences = loader.load_and_index_file(law_file)

    assert len(evidences) == 3
    assert kb.count() == 3


def test_index_metadata_does_not_leak_none_article(tmp_path):
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    loader = KnowledgeLoader(kb)
    loader.index(loader.split_text("没有条号的说明文字。", source="说明"))

    doc, _ = kb.similarity_search("说明文字", k=1)[0]
    assert "article" not in doc.metadata  # 不是 article=None，而是完全没有这个键
    assert doc.metadata["source"] == "说明"


def test_index_empty_list_does_not_touch_database(tmp_path):
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    assert KnowledgeLoader(kb).index([]) == []
    assert kb.count() == 0


def test_reindexing_is_idempotent_and_does_not_duplicate(tmp_path):
    # 2026-10-10 修正：之前这个测试叫 test_reindexing_appends_duplicates_by_design，
    # 断言的是 kb.count() == 6（旧版本确实会追加重复数据，这是当时的已知、被接受的行为）。
    # 现在 KnowledgeLoader.index() 用内容算出确定性 id 并以 ids= 调用
    # DenseBackend.add_texts → langchain_chroma.Chroma.add_texts，后者内部统一走
    # self._collection.upsert(...)（已对照 langchain-ai/langchain 仓库源码确认，见
    # rag/knowledge_loader.py::index() 的 docstring），upsert 对相同 id 是覆盖写入，
    # 所以重复加载同一份文件不应该让文档数量翻倍。
    law_file = tmp_path / "劳动合同法.txt"
    law_file.write_text(SAMPLE_LAW, encoding="utf-8")
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    loader = KnowledgeLoader(kb)

    loader.load_and_index_file(law_file)
    loader.load_and_index_file(law_file)

    assert kb.count() == 3  # 不是 6：第二次加载覆盖了第一次写入的同一批 id，不是新增


def test_evidence_id_is_deterministic_and_content_sensitive(tmp_path):
    """`_evidence_id()` 是整个幂等性机制的基础，单独测试它的两个关键性质：
    相同内容产出相同 id（否则 upsert 不会命中同一条记录），不同内容产出不同 id
    （否则会把两条不同的法条互相覆盖，造成数据丢失，比"不去重"更糟）。
    """
    loader = KnowledgeLoader(DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma"))
    a1 = loader.split_text(SAMPLE_LAW, source="劳动合同法")
    a2 = loader.split_text(SAMPLE_LAW, source="劳动合同法")

    ids_1 = [loader._evidence_id(e) for e in a1]
    ids_2 = [loader._evidence_id(e) for e in a2]
    assert ids_1 == ids_2  # 同样内容，两次切分出来的 id 必须完全一致
    assert len(set(ids_1)) == len(ids_1)  # 同一批里内容不同的条文，id 不能相撞

    # 哪怕只改一个字，id 也必须变化，否则会错误地覆盖另一条法条的内容
    tweaked = SAMPLE_LAW.replace("百分之八十", "百分之九十")
    tweaked_evidences = loader.split_text(tweaked, source="劳动合同法")
    tweaked_ids = [loader._evidence_id(e) for e in tweaked_evidences]
    assert tweaked_ids != ids_1


def test_evidence_id_differs_by_source_even_with_same_content(tmp_path):
    """2026-10-10 补充（用户复核时明确要求）：`_evidence_id()` 是对
    `(source, article, content) 一起算的，不能只看 content——否则两份不同法律
    文件里字面完全相同的条文会被错误地当成"同一条"，互相覆盖，丢数据。
    之前只测过"改内容→id变"，没测过"内容不变、只改 source→id 也要变"，这里补上。
    """
    loader = KnowledgeLoader(DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma"))
    same_text = "乙方应当遵守用人单位的规章制度。"
    e_from_a = Evidence(content=same_text, source="法A", article="第一条")
    e_from_b = Evidence(content=same_text, source="法B", article="第一条")

    assert loader._evidence_id(e_from_a) != loader._evidence_id(e_from_b)


def test_evidence_id_differs_by_article_even_with_same_content_and_source(tmp_path):
    """同上，变量换成只改 `article`（同一份法律文件内部，不同条号恰好写了
    完全相同的一句话，这在真实法律文本里不是不可能——比如多处"依照本法有关
    规定执行"这类套话）。"""
    loader = KnowledgeLoader(DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma"))
    same_text = "依照本法有关规定执行。"
    e_article_1 = Evidence(content=same_text, source="法A", article="第一条")
    e_article_2 = Evidence(content=same_text, source="法A", article="第二条")

    assert loader._evidence_id(e_article_1) != loader._evidence_id(e_article_2)


def test_index_called_directly_twice_with_same_evidences_list_does_not_duplicate(tmp_path):
    """2026-10-10 补充：之前验证幂等性的测试
    （`test_reindexing_is_idempotent_and_does_not_duplicate`）都是经
    `load_and_index_file()` 间接测的，会同时带上"读文件""切分"两步，不够
    聚焦。这里直接构造一份 `Evidence` 列表，两次调用 `index()` 本身，隔离出
    "index() 这一个方法是否幂等"这个最小问题，不依赖文件 I/O 或切分逻辑。
    """
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    loader = KnowledgeLoader(kb)
    evidences = [
        Evidence(content="第一条内容。", source="法A", article="第一条"),
        Evidence(content="第二条内容。", source="法A", article="第二条"),
    ]

    loader.index(evidences)
    assert kb.count() == 2

    loader.index(evidences)  # 完全相同的列表，再调用一次
    assert kb.count() == 2  # 不是 4


def test_changing_chunk_boundaries_leaves_orphaned_old_chunks_unless_reset(tmp_path):
    """2026-10-10 补充（用户复核时特别要求的场景，目前最重要的一个缺口）：
    upsert 只能覆盖"id 还存在"的记录，没办法知道"这个 id 以前存在过、现在不该
    存在了"——如果同一条超长法条先用一种 chunk_size 切分并索引，之后换了不同
    的 chunk_size 重新索引（切分边界变了，产出的 part 内容和之前不完全一样），
    旧的 part 对应的 id 不会被自动清除，会和新的 part 同时留在库里，变成
    "孤儿记录"。这个限制必须被测试显式钉住，不能只写在文档里口头说——
    不然很容易被误以为"反正有幂等性，怎么用都安全"。
    """
    long_article = "第一条 " + "违反规章制度的，用人单位可以解除劳动合同。" * 20
    law_file = tmp_path / "法A.txt"
    law_file.write_text(long_article, encoding="utf-8")

    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")

    # 第一次：用较小的 chunk_size 切分并索引
    loader_small_chunks = KnowledgeLoader(kb, chunk_size=100, chunk_overlap=20)
    first_evidences = loader_small_chunks.load_and_index_file(law_file)
    count_after_first = kb.count()
    assert len(first_evidences) > 1  # 确认真的被切成了多片，不是只有一片
    assert count_after_first == len(first_evidences)

    # 第二次：换一个不同的 chunk_size 重新索引同一个文件（边界变了，
    # 产出的 part 内容大概率和第一次不完全相同）
    loader_large_chunks = KnowledgeLoader(kb, chunk_size=200, chunk_overlap=20)
    second_evidences = loader_large_chunks.load_and_index_file(law_file)
    count_after_second = kb.count()

    # 如果 upsert 真的能"同步"全部内容（旧的失效 part 自动被清理），这里应该
    # 等于 len(second_evidences)；但实际上旧的 part 不会被自动删除，所以库里
    # 的数量是"旧的 + 新增的"里没有被 id 覆盖掉的那部分，必然 > 只有新切分这一批——
    # 这正是本测试要钉住的限制：**不要以为幂等写入=自动同步/自动清理**。
    assert count_after_second > len(second_evidences), (
        "如果这个断言失败（库里数量刚好等于新切分的数量），说明 upsert 的覆盖范围"
        "变了，或者本次切分恰好产出了和上次完全相同的 id——需要重新检查这个假设"
        "是否还成立，而不是直接删掉这条测试"
    )

    # 验证 reset() 是清理孤儿记录的正确方式：清空后只写入当前这一批，数量应该
    # 精确等于 len(second_evidences)，不再残留第一次的旧 part。
    kb.reset()
    loader_large_chunks.index(second_evidences)
    assert kb.count() == len(second_evidences)


def test_evidence_id_differs_by_part_even_with_identical_content(tmp_path):
    """2026-10-10 第二次补充（用户本地真实环境跑出来的问题）：同一条法条如果内容
    高度重复（比如同一句话连续出现多次），二次切分出来的多个 part 可能逐字相同；
    如果 `_evidence_id()` 不区分 `part`，这些 part 会算出完全相同的 id，同一批
    写入时会被 chromadb 判定为批内 id 重复而报 `DuplicateIDError`（这是用户本地
    `pytest` 实测复现的真实报错，不是推测）。这里直接构造两个 (source, article,
    content) 完全相同、只有 `metadata["part"]` 不同的 Evidence，钉住"id 必须因
    part 不同而不同"这个性质，不依赖真实的 `RecursiveCharacterTextSplitter`
    是否真的会切出重复内容（那是集成层面的事，这里只测 `_evidence_id()` 本身）。
    """
    loader = KnowledgeLoader(DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma"))
    same_text = "违反规章制度的，用人单位可以解除劳动合同。"
    part_1 = Evidence(content=same_text, source="法A", article="第一条", metadata={"part": 1, "parts": 3})
    part_2 = Evidence(content=same_text, source="法A", article="第一条", metadata={"part": 2, "parts": 3})

    assert loader._evidence_id(part_1) != loader._evidence_id(part_2)

    # 端到端确认：这两个 part 一起 index() 不会因为内容相同而互相覆盖或报错，
    # 两条都应该被当成独立记录写入。
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma2")
    loader2 = KnowledgeLoader(kb)
    loader2.index([part_1, part_2])
    assert kb.count() == 2


def test_index_deduplicates_literal_duplicate_evidences_within_one_call(tmp_path):
    """2026-10-10 第二次补充：如果同一次 `index()` 调用里，传入的 `evidences`
    列表本身包含两条 (source, article, part, content) 完全相同的记录——不是切分
    算法产出的、位置不同但内容相同的片段（上一条测试覆盖的场景），而是调用方
    真的把同一条记录放了两次——这两条记录的 id 必然相同。这里验证 `index()`
    的处理方式是按 id 去重、只保留一条写入（不报错、也不会凭空生成随机 id
    把它们强行区分开，否则会破坏"相同内容=相同 id"这条幂等性的基础）。
    """
    kb = DenseBackend(FakeEmbeddings(), persist_directory=tmp_path / "chroma")
    loader = KnowledgeLoader(kb)
    duplicate = Evidence(content="第一条内容。", source="法A", article="第一条")

    loader.index([duplicate, duplicate])  # 完全同一个对象，重复放进同一个列表两次
    assert kb.count() == 1  # 不是 2：按 id 去重，只写入一条

    # 再次用等价（不同对象、但字段完全相同）的 Evidence 重复索引，
    # 确认幂等性没有被这次的去重逻辑破坏：id 仍然稳定，upsert 命中同一条记录。
    equivalent = Evidence(content="第一条内容。", source="法A", article="第一条")
    loader.index([equivalent])
    assert kb.count() == 1
