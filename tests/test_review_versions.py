"""ReviewVersions 版本记录修复的测试。

背景：修复前 `workflows/review_workflow.py::report_assembly` 永远用
`ReviewVersions()`（零参数，全部字段为 None）构造报告，评估基准做"优化
前后对比"时无法区分两次报告分别对应哪个版本的 LLM/Prompt/规则集/知识库。
本次修复让这四个字段分别从 `reviewer.llm_client.model`、
`prompts.review.PROMPT_VERSION`、`rule_checker.ruleset_version`、
`data/knowledge/VERSION` 文件取真实值。

**本文件测试范围的限制（如实说明，不是本次新引入的限制）**：
`workflows/review_workflow.py` 模块顶层 `from langgraph.graph import ...`，
本沙箱没有装 `langgraph`，这个模块本身在这里无法 import，所以无法在这里
直接测试 `report_assembly` 节点组装出的 `ReviewVersions` 整体效果（那需要
真实跑一次 LangGraph 图）。本文件只测试"修复用到的三个可独立导入的部件"：
    - `rules.checker.RULESET_VERSION`（不需要 langgraph，只需要 schemas）
    - `prompts.review.PROMPT_VERSION`（不需要 langgraph）
    - `data/knowledge/VERSION` 文件本身存在且内容非空（`_read_knowledge_base_version`
      这个辅助函数定义在 workflows/review_workflow.py 里，逻辑只有两行文件读取，
      本文件不重复 import 那个模块，而是直接验证它读取的目标文件本身符合预期）。
完整的端到端验证（真的跑一次 `run_review()`，检查返回的 `ReviewReport.versions`
四个字段确实非空）需要装好 langgraph/langchain/openai/chromadb 的本地环境，
留给 docs/EVAL_DIAGNOSTICS.md 里的本地运行说明。
"""

from pathlib import Path

from config import settings
from rules.checker import RULESET_VERSION, RuleChecker
from rules.probation_duration import RULE_ID as PROBATION_DURATION_RULE_ID
from rules.probation_salary import RULE_ID as PROBATION_SALARY_RULE_ID
from prompts.review import PROMPT_VERSION


def test_ruleset_version_contains_both_registered_rule_ids():
    assert PROBATION_SALARY_RULE_ID in RULESET_VERSION
    assert PROBATION_DURATION_RULE_ID in RULESET_VERSION


def test_ruleset_version_is_deterministic_regardless_of_rule_order():
    # RULESET_VERSION 是模块加载时算好的常量，这里验证的是"算法本身"
    # 对顺序不敏感，而不是重新触发模块加载。
    assert RULESET_VERSION == "+".join(sorted([PROBATION_SALARY_RULE_ID, PROBATION_DURATION_RULE_ID]))


def test_rule_checker_instance_exposes_ruleset_version():
    checker = RuleChecker()
    assert checker.ruleset_version == RULESET_VERSION


def test_prompt_version_is_a_non_empty_string():
    assert isinstance(PROMPT_VERSION, str)
    assert len(PROMPT_VERSION) > 0


def test_knowledge_base_version_file_exists_and_is_non_empty():
    version_file = settings.KNOWLEDGE_DIR / "VERSION"
    assert version_file.exists(), "data/knowledge/VERSION 文件应该存在，供 _read_knowledge_base_version 读取"
    content = version_file.read_text(encoding="utf-8").strip()
    assert content != ""


def test_read_knowledge_base_version_logic_returns_none_when_file_missing(tmp_path):
    """直接复现 _read_knowledge_base_version 的读取逻辑（不 import workflows 模块，
    见本文件顶部说明），验证"文件不存在时返回 None、不抛异常"这个容错行为。
    """
    version_file = tmp_path / "VERSION"

    def read_knowledge_base_version(path: Path):
        try:
            return path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    assert read_knowledge_base_version(version_file) is None

    version_file.write_text("kb-test-01\n", encoding="utf-8")
    assert read_knowledge_base_version(version_file) == "kb-test-01"
