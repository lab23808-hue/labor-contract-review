"""测试分层：按文件名给每个测试自动打上层级标记（说明见 tests/README.md）。

这样不需要在每个测试文件里手写 pytestmark。新增测试文件时必须在下面的
TEST_LAYERS 里登记，否则收集阶段会直接报错提醒——避免测试越加越没有分层。

真实端到端测试不在 pytest 里，见 tests/README.md 的"第四层"。
"""

import pytest

TEST_LAYERS = {
    "unit": [
        "test_schemas.py",
        "test_clause_splitter.py",
        "test_document_parser.py",
        "test_contract.py",
        "test_config_settings.py",
        "test_llm_client.py",
        "test_llm_prompts.py",
        "test_review_schemas.py",
        "test_review_reviewer.py",
        "test_rag_embedding.py",
        "test_rules_probation_salary.py",
        "test_rules_probation_duration.py",
        "test_rules_checker.py",
        "test_rules_merge.py",
        "test_risk_diff.py",
        "test_validate_knowledge_base.py",
        "test_review_versions.py",
        "test_eval_schemas.py",
        "test_eval_generator.py",
        "test_eval_rules_diagnostics.py",
        "test_run_eval_scripts.py",
    ],
    "module": [
        "test_parser_integration.py",
        "test_clause_integration.py",
        "test_rag_database.py",
        "test_rag_loader.py",
        "test_rag_retrieval.py",
        "test_rag_bm25_index.py",
        "test_api_dependencies.py",
        "test_api_contracts.py",
    ],
    "graph": [
        "test_review_pipeline.py",
        "test_api_full_flow.py",
    ],
}

_LAYER_BY_FILE = {filename: layer for layer, files in TEST_LAYERS.items() for filename in files}


def pytest_collection_modifyitems(items):
    for item in items:
        # nodeid 形如 "tests/test_x.py::test_name"，取出文件名
        filename = item.nodeid.split("::", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
        layer = _LAYER_BY_FILE.get(filename)
        if layer is None:
            raise pytest.UsageError(
                f"测试文件 {filename} 还没有分层：请把它登记到 tests/conftest.py 的 TEST_LAYERS 里"
                "（unit / module / graph），分层含义见 tests/README.md"
            )
        item.add_marker(getattr(pytest.mark, layer))
