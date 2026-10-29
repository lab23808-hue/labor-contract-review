"""config/settings.py 的单元测试：默认值集中管理，且各模块确实引用它、仍可覆盖。"""

import ast
import inspect
from pathlib import Path

from domain.agents.review_agent import ClauseReviewer
from config import settings
from infra.storage import ContractManager
from infra.storage.manager import DEFAULT_ROOT_DIR
from domain.document.splitter import ClauseSplitter
from infra.llm.client import DEFAULT_DEEPSEEK_MODEL
from retrieval import DEFAULT_COLLECTION_NAME, DEFAULT_PERSIST_DIR
from retrieval.embedding import DEFAULT_MODEL_NAME
from retrieval.knowledge_loader import KnowledgeLoader
from retrieval.retriever import LegalKnowledgeRetriever


def _default_of(func, param_name):
    return inspect.signature(func).parameters[param_name].default


# ---------- settings 本身 ----------

def test_project_root_points_at_the_real_project_root():
    assert (settings.PROJECT_ROOT / "src" / "config" / "settings.py").is_file()


def test_data_directories_live_under_data_dir():
    assert settings.DATA_DIR == settings.PROJECT_ROOT / "data"
    assert settings.KNOWLEDGE_DIR == settings.DATA_DIR / "knowledge"
    assert settings.CHROMA_DIR == settings.DATA_DIR / "index" / "chroma"
    assert settings.CONTRACTS_DIR == settings.DATA_DIR / "runtime" / "contracts"


def test_settings_holds_no_secrets():
    # API Key 只能来自环境变量 / .env，不能出现在 settings 里
    names = [n.upper() for n in dir(settings) if not n.startswith("_")]
    assert not any("KEY" in n or "TOKEN" in n or "SECRET" in n for n in names)


def test_settings_only_depends_on_standard_library():
    tree = ast.parse(Path(settings.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"pathlib"}


# ---------- 各模块的默认值来自 settings ----------

def test_module_level_defaults_come_from_settings():
    assert DEFAULT_ROOT_DIR == settings.CONTRACTS_DIR
    assert DEFAULT_PERSIST_DIR == settings.CHROMA_DIR
    assert DEFAULT_COLLECTION_NAME == settings.CHROMA_COLLECTION_NAME
    assert DEFAULT_MODEL_NAME == settings.EMBEDDING_MODEL_NAME
    assert DEFAULT_DEEPSEEK_MODEL == settings.LLM_MODEL_NAME


def test_constructor_defaults_come_from_settings():
    assert _default_of(ClauseSplitter.__init__, "chunk_size") == settings.CLAUSE_CHUNK_SIZE
    assert _default_of(ClauseSplitter.__init__, "chunk_overlap") == settings.CLAUSE_CHUNK_OVERLAP
    assert _default_of(KnowledgeLoader.__init__, "chunk_size") == settings.KNOWLEDGE_CHUNK_SIZE
    assert _default_of(KnowledgeLoader.__init__, "chunk_overlap") == settings.KNOWLEDGE_CHUNK_OVERLAP
    assert _default_of(LegalKnowledgeRetriever.__init__, "top_k") == settings.RETRIEVAL_TOP_K
    assert _default_of(ClauseReviewer.__init__, "top_k") == settings.RETRIEVAL_TOP_K


def test_default_splitters_use_the_configured_sizes():
    splitter = ClauseSplitter()
    assert splitter.chunk_size == settings.CLAUSE_CHUNK_SIZE
    assert splitter.chunk_overlap == settings.CLAUSE_CHUNK_OVERLAP


# ---------- 仍然可以覆盖 ----------

def test_constructor_arguments_still_override_defaults():
    splitter = ClauseSplitter(chunk_size=120, chunk_overlap=10)
    assert (splitter.chunk_size, splitter.chunk_overlap) == (120, 10)


def test_contract_manager_root_dir_can_be_overridden(tmp_path):
    manager = ContractManager(root_dir=tmp_path / "custom")
    assert manager.root_dir == tmp_path / "custom"
    assert manager.root_dir != settings.CONTRACTS_DIR
