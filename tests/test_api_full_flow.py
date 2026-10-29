"""API 第一阶段全链路集成测试。

验证 4 个已实现的接口真的能串成一条完整链路，而不是各自独立能跑通就行：

    POST /contracts
      → contract_id
    POST /contracts/{id}/parse
      → Clause[]
    GET /contracts/{id}/clauses
      → 必须和 parse 的结果一致（同一份 clauses.json）
    POST /contracts/{id}/review
      → ReviewReport，contract_id 与上面贯通一致

本文件复用与 tests/test_api_contracts.py 相同的替身策略（FakeEmbeddings /
指向 tmp_path 的真实 DenseBackend / 不连网络的 DeepSeek 客户端替身 /
不调用真实 LLM 的 reviewer 替身），ContractManager 用真实实现（指向
tmp_path），RuleChecker 用真实实现（无外部依赖）。POST /review 会真实跑一遍
review/pipeline.py 里的 LangGraph（build_graph/run_review），只有 LLM 与
检索是假的——这正是项目里"graph"这一测试层级的定义，所以这个文件登记在
tests/conftest.py 的 graph 分层下。

不修改 ContractManager / Parser / ClauseSplitter / RAG / LLM / RuleChecker /
review/pipeline.py。
"""

import io

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_contract_manager, get_reviewer
from config import settings
from infra.storage import ContractManager
from infra.llm.client import OpenAICompatibleClient
from retrieval import DenseBackend
from core import Clause, ReviewResult, ReviewSource, RiskLevel
from tests._rag_fakes import FakeEmbeddings

# 三条款样例文本，与 tests/test_api_contracts.py 保持一致（同一份
# scripts/_samples.py::RAG_RETRIEVAL_SAMPLE），避免链路测试用一份自造数据。
_SAMPLE_CONTRACT_TEXT = (
    "第一条 试用期工资\n"
    "乙方试用期为三个月，试用期工资为正式工资标准的百分之五十。\n\n"
    "第二条 工作地点\n"
    "乙方工作地点为深圳市。甲方可以根据经营需要随时调整乙方工作地点，乙方应无条件服从。\n\n"
    "第三条 竞业限制\n"
    "乙方在劳动合同解除或者终止后二年内，不得到与甲方有竞争关系的单位任职，甲方无需向乙方支付任何经济补偿。\n"
)


class _FakeDeepSeekClient(OpenAICompatibleClient):
    """DeepSeek 客户端的测试替身：不调用父类 __init__，不连接真实服务。"""

    def __init__(self) -> None:  # noqa: super-init-not-called
        self.model = "fake-model"
        self._client = None


class _FakeReviewer:
    """ClauseReviewer 的测试替身：不检索、不调用真实 LLM，返回确定性的 ReviewResult。"""

    def __init__(self) -> None:
        self.reviewed_clause_ids: list[str] = []

    def review(self, clause: Clause) -> ReviewResult:
        self.reviewed_clause_ids.append(clause.clause_id)
        return ReviewResult(
            clause_id=clause.clause_id,
            risk=False,
            risk_level=RiskLevel.NONE,
            reason="测试替身：未调用真实 LLM",
            legal_basis=[],
            suggestion="",
            source=ReviewSource.LLM,
        )


def _patch_heavy_builders(monkeypatch, tmp_path):
    # 2026-10-12 BM25 正式接入后生产默认变成 "bm25"；本文件测的是 review 全链路
    # 贯通本身（reviewer 另外被替身化），不是检索策略，显式钉回 "dense"，让
    # 下面构造的 DenseBackend 替身真的会被用到，行为与接入前一致。
    monkeypatch.setattr(settings, "RETRIEVAL_STRATEGY", "dense")
    monkeypatch.setattr("api.dependencies.build_embedder", lambda: FakeEmbeddings())
    monkeypatch.setattr("api.dependencies.KnowledgeLoader.count_evidences", lambda self, directory: 0)
    monkeypatch.setattr(
        "api.dependencies.DenseBackend",
        lambda embedding_function: DenseBackend(
            embedding_function=embedding_function,
            persist_directory=tmp_path / "chroma",
            collection_name="test_api_full_flow",
        ),
    )
    monkeypatch.setattr("api.dependencies.build_deepseek_client", lambda: _FakeDeepSeekClient())


@pytest.fixture
def client(monkeypatch, tmp_path):
    """重对象已替身化、ContractManager 指向 tmp_path 的真实实例。"""
    _patch_heavy_builders(monkeypatch, tmp_path)
    app.dependency_overrides[get_contract_manager] = lambda: ContractManager(root_dir=tmp_path / "contracts")
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_contract_manager, None)


@pytest.fixture
def review_client(client):
    """在 client 基础上把 reviewer 也换成不调用真实 LLM 的替身；RuleChecker 保持真实。"""
    fake_reviewer = _FakeReviewer()
    app.dependency_overrides[get_reviewer] = lambda: fake_reviewer
    try:
        yield client, fake_reviewer
    finally:
        app.dependency_overrides.pop(get_reviewer, None)


def test_full_flow_contract_id_and_clauses_stay_consistent_end_to_end(review_client):
    """完整走一遍 上传 → parse → clauses → review，验证四个接口之间贯通一致。"""
    client, fake_reviewer = review_client

    # 1) 上传 → 拿到 contract_id
    upload_response = client.post(
        "/contracts",
        files={"file": ("劳动合同.txt", io.BytesIO(_SAMPLE_CONTRACT_TEXT.encode("utf-8")), "text/plain")},
    )
    assert upload_response.status_code == 201
    contract = upload_response.json()
    contract_id = contract["contract_id"]
    assert contract["filename"] == "劳动合同.txt"

    # 2) parse → 得到 Clause[]
    parse_response = client.post(f"/contracts/{contract_id}/parse")
    assert parse_response.status_code == 200
    parsed_clauses = parse_response.json()
    assert len(parsed_clauses) == 3
    assert all(c["contract_id"] == contract_id for c in parsed_clauses)

    # 3) GET clauses → 必须和 parse 的结果完全一致（同一份 clauses.json）
    get_clauses_response = client.get(f"/contracts/{contract_id}/clauses")
    assert get_clauses_response.status_code == 200
    assert get_clauses_response.json() == parsed_clauses

    # 4) review → ReviewReport，contract_id 贯通，results/failed_clauses 结构正确
    review_response = client.post(f"/contracts/{contract_id}/review")
    assert review_response.status_code == 200
    report = review_response.json()
    assert report["contract_id"] == contract_id
    assert report["failed_clauses"] == []

    parsed_clause_ids = {c["clause_id"] for c in parsed_clauses}
    llm_result_clause_ids = {r["clause_id"] for r in report["results"] if r["source"] == "llm"}
    # review 阶段审查的条款，必须和 parse/clauses 阶段产出的是同一批 clause_id ——
    # 这是链路贯通的核心断言：不是"数量凑巧相等"，而是 id 集合完全相同。
    assert llm_result_clause_ids == parsed_clause_ids
    assert set(fake_reviewer.reviewed_clause_ids) == parsed_clause_ids


def test_full_flow_unknown_contract_id_fails_reasonably_at_every_downstream_step(review_client):
    """异常链路：一个从未上传过的 contract_id，在 parse / clauses / review 三步
    都应该得到合理的 HTTP 错误（本项目里统一是 404），而不是在某一步意外变成 500。
    """
    client, _ = review_client
    fake_contract_id = "f" * 32

    assert client.post(f"/contracts/{fake_contract_id}/parse").status_code == 404
    assert client.get(f"/contracts/{fake_contract_id}/clauses").status_code == 404
    assert client.post(f"/contracts/{fake_contract_id}/review").status_code == 404
