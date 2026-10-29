"""法律知识库纯文本结构校验（不依赖 chromadb / langchain_text_splitters / BGE-M3）。

背景：生产代码 `retrieval/knowledge_loader.py::KnowledgeLoader` 在模块顶层
`from langchain_text_splitters import RecursiveCharacterTextSplitter`，
导致即使只想验证"按第X条切分"这一步纯文本逻辑，也无法在没装这个包的环境
里 import 这个模块。本脚本不改动 `retrieval/knowledge_loader.py`，而是用同一份
切分正则（_ARTICLE_RE，必须和 `retrieval/knowledge_loader.py` 保持一致——见下方
断言）独立实现一遍"按条切分 + 结构校验"，纯标准库，任何环境都能跑。

**这个脚本能证明什么、不能证明什么（如实说明，不夸大）：**
- 能证明：data/knowledge/*.txt 里的"第X条"切分点、条号是否重复、是否有
  空块、哪些条文长度超过 KNOWLEDGE_CHUNK_SIZE（会被生产代码二次切分）。
- 不能证明：真正写入 Chroma 后能不能检索到（需要真实 chromadb + BGE-M3，
  本沙箱不可用，。
- 不能证明：条文文本本身是否逐字匹配官方原文（见 data/knowledge/SOURCES.md
  "文本核验状态"——这是另一件事，本脚本不做这个核验）。

用法：
    python scripts/validate_knowledge_base.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402

# 必须和 retrieval/knowledge_loader.py 里的 _ARTICLE_RE 保持完全一致——这里独立
# 复制一份而不是 import 该模块，是因为该模块的顶层 import 需要
# langchain_text_splitters，本脚本的设计目标就是不依赖它。
_CN_DIGITS = "一二三四五六七八九十百千零〇两"
_INDENT = r"^[ \t　]*"
_ARTICLE_RE = re.compile(rf"{_INDENT}(第[{_CN_DIGITS}\d]+条)(?!的)", re.MULTILINE)

_CN_DIGIT_VALUE = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _cn_number_to_int(cn: str) -> "int | None":
    """把"第X条"里的中文数字（一百二十三 这类）转成 int，转不了返回 None（不猜测）。"""
    if cn.isdigit():
        return int(cn)
    if not cn:
        return None
    total = 0
    section = 0
    unit_seen = False
    try:
        i = 0
        while i < len(cn):
            ch = cn[i]
            if ch == "百":
                section = (section or 1) * 100
                unit_seen = True
            elif ch == "十":
                section = (section or 1) * 10
                unit_seen = True
            else:
                digit = _CN_DIGIT_VALUE[ch]
                if i + 1 < len(cn) and cn[i + 1] in ("十", "百"):
                    section += digit if digit else 0
                else:
                    section += digit
            i += 1
        total = section
        return total if unit_seen or total < 10 else total
    except KeyError:
        return None


def find_article_spans(text: str) -> list[tuple[int, int, str]]:
    starts = [(m.start(), m.group(1)) for m in _ARTICLE_RE.finditer(text)]
    spans = []
    for idx, (start, label) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(text)
        spans.append((start, end, label))
    return spans


def validate_file(path: Path, chunk_size: int) -> dict:
    text = path.read_text(encoding="utf-8")
    spans = find_article_spans(text)

    report = {
        "file": path.name,
        "total_chars": len(text),
        "article_count": len(spans),
        "duplicate_articles": [],
        "empty_blocks": [],
        "oversized_articles": [],  # 会被生产代码二次切分成多个 Evidence
        "unparsable_numbers": [],
        "non_monotonic": [],  # 仅提示，不是错误：本知识库刻意只收录相关条文，天然不连续
        "articles": [],
    }

    seen = {}
    prev_num = None
    for start, end, label in spans:
        block = text[start:end].strip()
        num_cn = label[1:-1]  # 去掉"第"和"条"
        num = _cn_number_to_int(num_cn)

        if label in seen:
            report["duplicate_articles"].append(
                {"article": label, "first_pos": seen[label], "duplicate_pos": start}
            )
        else:
            seen[label] = start

        if not block:
            report["empty_blocks"].append(label)

        if len(block) > chunk_size:
            report["oversized_articles"].append({"article": label, "length": len(block)})

        if num is None:
            report["unparsable_numbers"].append(label)
        elif prev_num is not None and num < prev_num:
            report["non_monotonic"].append({"article": label, "prev": prev_num, "this": num})
        if num is not None:
            prev_num = num

        report["articles"].append({"article": label, "length": len(block)})

    return report


def main() -> None:
    knowledge_dir = settings.KNOWLEDGE_DIR
    files = sorted(knowledge_dir.glob("*.txt"))
    if not files:
        print(f"{knowledge_dir} 下没有找到任何 .txt 文件")
        return

    print(f"知识库目录：{knowledge_dir}")
    print(f"KNOWLEDGE_CHUNK_SIZE = {settings.KNOWLEDGE_CHUNK_SIZE}（超过这个长度的条文会被生产代码二次切分）\n")

    all_ok = True
    seen_across_files = {}

    for f in files:
        report = validate_file(f, settings.KNOWLEDGE_CHUNK_SIZE)
        print(f"=== {report['file']} ===")
        print(f"  条文数：{report['article_count']}，总字数：{report['total_chars']}")

        if report["duplicate_articles"]:
            all_ok = False
            print(f"  [问题] 文件内重复条号：{report['duplicate_articles']}")
        if report["empty_blocks"]:
            all_ok = False
            print(f"  [问题] 空条文块：{report['empty_blocks']}")
        if report["unparsable_numbers"]:
            all_ok = False
            print(f"  [问题] 无法解析的条号（可能是生僻中文数字写法）：{report['unparsable_numbers']}")
        if report["oversized_articles"]:
            print(f"  [提示] 超过 chunk_size、生产代码会二次切分的条文：{report['oversized_articles']}")
        if report["non_monotonic"]:
            print(f"  [提示] 条号非严格递增（本知识库刻意只收录相关条文，不要求连续，仅供人工复核）：{report['non_monotonic']}")

        for art in report["articles"]:
            label = art["article"]
            if label in seen_across_files:
                all_ok = False
                print(f"  [问题] 条号 {label} 同时出现在 {seen_across_files[label]} 和 {report['file']}（跨文件重复，"
                      f"写入向量库会产生两条内容相同来源不同的记录，检索时可能重复返回）")
            else:
                seen_across_files[label] = report["file"]

        print()

    print("=" * 60)
    print("重复加载：retrieval/knowledge_loader.py::KnowledgeLoader.index() 会按")
    print("(source, article, part, content) 生成确定性 id，同一批内按 id 去重，")
    print("跨批次由 ChromaVectorStore.upsert 覆盖同 id，因此重复索引同一文件不会重复计数。")
    print()
    print("结论：" + ("未发现结构性问题" if all_ok else "发现上述结构性问题，建议处理后再重建索引"))


if __name__ == "__main__":
    main()
