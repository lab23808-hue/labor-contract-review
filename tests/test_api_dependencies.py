"""api/dependencies.py 的测试。

只验证本次的 4 个要求：
    1. FastAPI 应用能够正常创建
    2. lifespan 能正常初始化依赖
    3. 依赖对象可以被路由层（通过 Depends）获取
    4. 重对象不是每次请求重新创建

不调用真实 DeepSeek，不下载真实 BGE-M3：
    - embedder      换成 tests/_rag_fakes.py 里的 FakeEmbeddings（确定性向量，无下载）
    - DenseBackend 仍然是真实类，但指向 tmp_path，避免读写 data/index/chroma 下的
      生产数据（这与项目里"真实 Chroma + 假 embedding"的 module 测试用法一致）
    - DeepSeek client 换成一个不触发真实网络请求的替身（跳过父类 __init__ 里的
      OpenAI(...) 构造；这些测试也不会调用它的 chat()）

RuleChecker、ClauseReviewer、ContractManager 都是真实类：它们的构造函数本身
不发起任何外部调用，不需要替身。
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.app import app as real_app
from api.dependencies import (
    AppState,
    build_app_state,
    get_contract_manager,
    get_reviewer,
    get_rule_checker,
    lifespan,
)
from config import settings
from infra.llm.client import OpenAICompatibleClient
from retrieval import BM25IndexBuildError, BM25Backend
from retrieval import DenseBackend
from domain.rules import RuleChecker
from tests._rag_fakes import FakeEmbeddings


class _FakeDeepSeekClient(OpenAICompatibleClient):
    """DeepSeek 客户端的测试替身：不调用父类 __init__，不连接真实服务。"""

    def __init__(self) -> None:  # noqa: super-init-not-called（就是不想跑真实的 OpenAI(...) 构造）
        self.model = "fake-model"
        self._client = None


def _patch_heavy_builders(monkeypatch, tmp_path):
    """把 build_app_state() 里会触发真实模型下载 / 真实网络调用的构造点换成替身。

    在 api.dependencies 模块里打补丁（而不是在 rag.embedding / llm.client 里），
    因为 build_app_state 是通过 `from rag.embedding import build_embedder` 这种
    方式把名字导入到自己的命名空间里调用的——要在"被调用的地方"打补丁。

    2026-10-12 BM25 正式接入后，生产默认的 settings.RETRIEVAL_STRATEGY 变成了
    "bm25"；这里显式钉回 "dense"，让本文件下面这几个针对 Chroma/BGE-M3 路径
    写的既有测试继续测的是它们本来要测的东西，不随生产默认值变化而改变含义。
    BM25 路径的新测试见下面 test_build_app_state_wires_bm25_backend_* 等。
    """
    monkeypatch.setattr(settings, "RETRIEVAL_STRATEGY", "dense")
    monkeypatch.setattr("api.dependencies.build_embedder", lambda: FakeEmbeddings())
    monkeypatch.setattr("api.dependencies.KnowledgeLoader.count_evidences", lambda self, directory: 0)
    monkeypatch.setattr(
        "api.dependencies.DenseBackend",
        lambda embedding_function: DenseBackend(
            embedding_function=embedding_function,
            persist_directory=tmp_path / "chroma",
            collection_name="test_api_dependencies",
        ),
    )
    monkeypatch.setattr("api.dependencies.build_deepseek_client", lambda: _FakeDeepSeekClient())


def test_api_app_can_be_created():
    """要求 1：FastAPI 应用能够正常创建（用的就是 api/app.py 里真实的 app 对象）。"""
    assert isinstance(real_app, FastAPI)
    assert real_app.router.lifespan_context is not None


def test_build_app_state_wires_existing_modules_together(monkeypatch, tmp_path):
    """build_app_state() 只是"接线"：把各业务模块的实例正确传给彼此，不改变它们的行为。"""
    _patch_heavy_builders(monkeypatch, tmp_path)

    state = build_app_state()

    assert isinstance(state, AppState)
    assert isinstance(state.rule_checker, RuleChecker)
    assert isinstance(state.knowledge_base, DenseBackend)
    assert state.retriever.knowledge_base is state.knowledge_base
    assert state.reviewer.retriever is state.retriever
    assert state.reviewer.llm_client is state.llm_client


def test_lifespan_initializes_app_state_on_real_app(monkeypatch, tmp_path):
    """要求 2：lifespan 能正常初始化依赖（用真实 api.app.app + 真实 lifespan）。"""
    _patch_heavy_builders(monkeypatch, tmp_path)

    with TestClient(real_app):
        # TestClient 作为上下文管理器使用时会触发 ASGI 的 startup 事件，即 lifespan
        assert isinstance(real_app.state.app_state, AppState)


def test_dependencies_return_same_instances_across_requests(monkeypatch, tmp_path):
    """要求 3 + 4：路由通过 Depends 拿到的重对象可以被正常获取，
    且两次请求之间是同一个实例（证明没有每次请求重新构造）。

    本阶段还没有正式的 /contracts 路由，这里临时挂一个只读探针路由，
    只用于验证依赖注入本身；不使用共享的 real_app，避免给生产 app 对象
    留下测试专用的路由。
    """
    _patch_heavy_builders(monkeypatch, tmp_path)

    probe_app = FastAPI(lifespan=lifespan)

    @probe_app.get("/_probe")
    def probe(
        contract_manager=Depends(get_contract_manager),
        reviewer=Depends(get_reviewer),
        rule_checker=Depends(get_rule_checker),
    ):
        return {
            "contract_manager_id": id(contract_manager),
            "reviewer_id": id(reviewer),
            "rule_checker_id": id(rule_checker),
        }

    with TestClient(probe_app) as client:
        first = client.get("/_probe").json()
        second = client.get("/_probe").json()

    assert first == second


# ---------- 2026-10-12 BM25 正式接入：按配置选择性初始化 ----------

def test_build_app_state_wires_bm25_backend_when_strategy_is_bm25(monkeypatch, tmp_path):
    """默认策略分支：RETRIEVAL_STRATEGY="bm25" 时不应该初始化 Chroma/BGE-M3，
    只应该从 settings.KNOWLEDGE_DIR 读取文本构建内存 BM25 索引。
    """
    embedder_calls: list[int] = []
    chroma_calls: list[int] = []
    monkeypatch.setattr(
        "api.dependencies.build_embedder",
        lambda: (embedder_calls.append(1), FakeEmbeddings())[1],
    )
    monkeypatch.setattr(
        "api.dependencies.DenseBackend",
        lambda embedding_function: (
            chroma_calls.append(1),
            DenseBackend(
                embedding_function=embedding_function,
                persist_directory=tmp_path / "chroma",
                collection_name="should_not_be_used",
            ),
        )[1],
    )
    monkeypatch.setattr("api.dependencies.build_deepseek_client", lambda: _FakeDeepSeekClient())
    monkeypatch.setattr(settings, "RETRIEVAL_STRATEGY", "bm25")

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "测试法律.txt").write_text(
        "第一条 这是第一条用于测试的内容，足够长，不会被当成空白。\n"
        "第二条 这是第二条用于测试的内容，和第一条完全不同。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "KNOWLEDGE_DIR", knowledge_dir)

    state = build_app_state()

    assert state.embedder is None
    assert state.knowledge_base is None
    assert isinstance(state.retriever.knowledge_base, BM25Backend)
    assert state.retriever.knowledge_base.count() == 2
    # 确认真的没有初始化 Chroma/BGE-M3，不只是配置写了 bm25
    assert embedder_calls == []
    assert chroma_calls == []


def test_build_app_state_raises_on_empty_knowledge_dir_under_bm25(monkeypatch, tmp_path):
    """空知识库必须让启动直接失败（BM25IndexBuildError），不能静默跑起来、
    也不能悄悄退化成 Dense。"""
    monkeypatch.setattr("api.dependencies.build_deepseek_client", lambda: _FakeDeepSeekClient())
    monkeypatch.setattr(settings, "RETRIEVAL_STRATEGY", "bm25")
    empty_dir = tmp_path / "empty_knowledge"
    empty_dir.mkdir()
    monkeypatch.setattr(settings, "KNOWLEDGE_DIR", empty_dir)

    with pytest.raises(BM25IndexBuildError):
        build_app_state()


def test_build_app_state_rejects_invalid_retrieval_strategy(monkeypatch):
    """非法的 RETRIEVAL_STRATEGY 取值必须直接报错，不能静默退化到某个默认策略。"""
    monkeypatch.setattr(settings, "RETRIEVAL_STRATEGY", "not_a_real_strategy")
    with pytest.raises(ValueError):
        build_app_state()
