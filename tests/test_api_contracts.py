"""api/routes/contracts.py 的测试：覆盖 POST /contracts、POST /contracts/{id}/parse、
GET /contracts/{id}/clauses、POST /contracts/{id}/review。

lifespan 启动时会构造全部 7 个重对象（即使这个接口用不到 embedder/Chroma/
DeepSeek），所以这里复用与 test_api_dependencies.py 相同的替身策略，把这几个
构造点换掉，避免真实下载 BGE-M3 / 调用真实 DeepSeek。

ContractManager 通过 FastAPI 的 dependency_overrides 换成指向 tmp_path 的
真实实例——这样测试产生的合同文件写在临时目录里，不会碰 data/contracts 下的
生产数据，同时也验证了"路由确实是通过依赖注入拿到 ContractManager"这件事。
"""

import io
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_contract_manager, get_reviewer
from config import settings
from contract import ContractManager
from llm.client import OpenAICompatibleClient
from rag.database import ChromaKnowledgeBase
from schemas import Clause, ContractStatus, ContractVersion, ReviewResult, ReviewSource, RiskLevel
from tests._rag_fakes import FakeEmbeddings


class _FakeDeepSeekClient(OpenAICompatibleClient):
    """DeepSeek 客户端的测试替身：不调用父类 __init__，不连接真实服务。"""

    def __init__(self) -> None:  # noqa: super-init-not-called
        self.model = "fake-model"
        self._client = None


class _FakeReviewer:
    """ClauseReviewer 的测试替身：不检索、不调用真实 LLM，返回确定性的 ReviewResult。

    记录被调用时传入的 clause_id，方便测试断言"确实是 run_review 内部调用了
    我们注入的这个 reviewer"，而不是路由自己算出了审查结果。
    """

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
    # 2026-10-12 BM25 正式接入后生产默认变成 "bm25"；本文件测的是路由本身
    # （/contracts 等），不是检索策略，显式钉回 "dense"，让下面构造的
    # ChromaKnowledgeBase 替身真的会被用到，行为与接入前一致。
    monkeypatch.setattr(settings, "RETRIEVAL_STRATEGY", "dense")
    monkeypatch.setattr("api.dependencies.build_embedder", lambda: FakeEmbeddings())
    monkeypatch.setattr(
        "api.dependencies.ChromaKnowledgeBase",
        lambda embedding_function: ChromaKnowledgeBase(
            embedding_function=embedding_function,
            persist_directory=tmp_path / "chroma",
            collection_name="test_api_contracts",
        ),
    )
    monkeypatch.setattr("api.dependencies.build_deepseek_client", lambda: _FakeDeepSeekClient())


@pytest.fixture
def client(monkeypatch, tmp_path):
    """一个可用的测试客户端：重对象已替身化，ContractManager 指向 tmp_path。"""
    _patch_heavy_builders(monkeypatch, tmp_path)
    contracts_dir = tmp_path / "contracts"
    app.dependency_overrides[get_contract_manager] = lambda: ContractManager(root_dir=contracts_dir)
    try:
        with TestClient(app) as c:
            yield c
    finally:
        # 全局共享的是同一个 app 对象，用完必须清理，否则会污染其他测试文件。
        app.dependency_overrides.pop(get_contract_manager, None)


@pytest.fixture
def review_client(client):
    """在 client 基础上，把 reviewer 也换成不调用真实 LLM 的替身。

    RuleChecker 不用换：它没有任何外部依赖（不检索、不调用 LLM），lifespan
    里构造出来的就是可以直接用的真实实例，这里不需要、也不应该替换它——
    题目要求"不修改 RuleChecker"，连测试里都应该用真的。
    """
    fake_reviewer = _FakeReviewer()
    app.dependency_overrides[get_reviewer] = lambda: fake_reviewer
    try:
        yield client, fake_reviewer
    finally:
        app.dependency_overrides.pop(get_reviewer, None)


def test_upload_txt_returns_201_with_correct_contract_fields(client):
    """要求 1 + 2：正常上传 txt → 201，返回的 Contract 字段正确。"""
    files = {"file": ("劳动合同.txt", io.BytesIO("这是一份测试合同文本".encode("utf-8")), "text/plain")}

    response = client.post("/contracts", files=files)

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "劳动合同.txt"
    assert body["file_format"] == "txt"
    assert body["status"] == ContractStatus.UPLOADED.value
    assert len(body["contract_id"]) == 32  # uuid4().hex
    assert body["size_bytes"] > 0
    assert len(body["sha256"]) == 64


def test_upload_is_actually_persisted_by_contract_manager(client, tmp_path):
    """要求 3：ContractManager 确实完成了文件落盘（不是 API 层自己伪造的返回值）。"""
    content = "劳动合同条款内容".encode("utf-8")
    files = {"file": ("sample.txt", io.BytesIO(content), "text/plain")}

    response = client.post("/contracts", files=files)
    contract_id = response.json()["contract_id"]

    contract_dir = tmp_path / "contracts" / contract_id
    saved_original = contract_dir / "original_file" / "sample.txt"
    metadata_file = contract_dir / "metadata.json"

    assert saved_original.is_file()
    assert saved_original.read_bytes() == content
    assert metadata_file.is_file()


def test_temp_upload_directory_is_removed_after_success(client, monkeypatch):
    """要求 4：请求处理完成后，API 层为这次上传创建的临时目录必须被清理掉。"""
    created_dirs: list[Path] = []
    original_mkdtemp = tempfile.mkdtemp

    def _tracking_mkdtemp(*args, **kwargs):
        d = original_mkdtemp(*args, **kwargs)
        created_dirs.append(Path(d))
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", _tracking_mkdtemp)

    files = {"file": ("a.txt", io.BytesIO(b"some contract text"), "text/plain")}
    response = client.post("/contracts", files=files)

    assert response.status_code == 201
    assert created_dirs, "路由应该调用过 tempfile.mkdtemp 创建临时目录"
    assert not created_dirs[0].exists(), "成功之后临时目录必须被删除"


def test_temp_upload_directory_is_removed_after_business_error(client, monkeypatch):
    """要求 4 + 5：ContractManager 判定为非法请求（缺扩展名）时同样要清理临时目录。"""
    created_dirs: list[Path] = []
    original_mkdtemp = tempfile.mkdtemp

    def _tracking_mkdtemp(*args, **kwargs):
        d = original_mkdtemp(*args, **kwargs)
        created_dirs.append(Path(d))
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", _tracking_mkdtemp)

    files = {"file": ("noext", io.BytesIO(b"content"), "text/plain")}
    response = client.post("/contracts", files=files)

    assert response.status_code == 422  # 没有有效扩展名，ContractManager 会拒绝
    assert created_dirs and not created_dirs[0].exists()


def test_empty_file_returns_400(client):
    """要求 5：空文件是一次不合法的请求，应该得到 4xx 而不是 500 或 201。"""
    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}

    response = client.post("/contracts", files=files)

    assert response.status_code == 400


def test_missing_file_field_returns_422(client):
    """要求 5：请求里完全没有带 file 字段，属于不合法请求，FastAPI 自身的校验会拦下来。"""
    response = client.post("/contracts")

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /contracts/{contract_id}/parse
# ---------------------------------------------------------------------------

# 复用项目已有的三条款样例文本（见 scripts/_samples.py::RAG_RETRIEVAL_SAMPLE），
# 保持测试数据和项目其他验证脚本一致，而不是自己再造一份。
_SAMPLE_CONTRACT_TEXT = (
    "第一条 试用期工资\n"
    "乙方试用期为三个月，试用期工资为正式工资标准的百分之五十。\n\n"
    "第二条 工作地点\n"
    "乙方工作地点为深圳市。甲方可以根据经营需要随时调整乙方工作地点，乙方应无条件服从。\n\n"
    "第三条 竞业限制\n"
    "乙方在劳动合同解除或者终止后二年内，不得到与甲方有竞争关系的单位任职，甲方无需向乙方支付任何经济补偿。\n"
)


def _upload(client, filename="劳动合同.txt", content: bytes = None) -> str:
    """上传一份合同，返回 contract_id（/parse 测试的公共前置步骤）。"""
    if content is None:
        content = _SAMPLE_CONTRACT_TEXT.encode("utf-8")
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    response = client.post("/contracts", files=files)
    assert response.status_code == 201, response.text
    return response.json()["contract_id"]


def test_parse_returns_200_with_clause_list(client):
    """要求 1 + 2：正常合同 → 200，返回的 Clause 列表内容正确。"""
    contract_id = _upload(client)

    response = client.post(f"/contracts/{contract_id}/parse")

    assert response.status_code == 200
    clauses = response.json()
    assert len(clauses) == 3  # 样例文本里明确的三条"第X条"
    assert all(c["contract_id"] == contract_id for c in clauses)
    assert len({c["clause_id"] for c in clauses}) == len(clauses)  # clause_id 互不重复
    assert clauses[0]["original_text"].startswith("第一条 试用期工资")


def test_parse_persists_parsed_text_and_clauses_via_contract_manager(client, tmp_path):
    """要求 3：parsed_text.txt / clauses.json 确实由 parse_contract / split_contract
    这两个现有业务函数生成并保存到磁盘，不是路由自己伪造的返回值。
    """
    contract_id = _upload(client)

    response = client.post(f"/contracts/{contract_id}/parse")
    clauses = response.json()

    contract_dir = tmp_path / "contracts" / contract_id
    parsed_text_file = contract_dir / "parsed_text.txt"
    clauses_file = contract_dir / "clauses.json"

    assert parsed_text_file.is_file()
    assert parsed_text_file.read_text(encoding="utf-8") == _SAMPLE_CONTRACT_TEXT
    assert clauses_file.is_file()
    assert len(clauses) == len(json.loads(clauses_file.read_text(encoding="utf-8")))


def test_parse_unknown_contract_id_returns_404(client):
    """要求 4：不存在的 contract_id 应该得到 404，而不是 500 或者其他状态码。"""
    fake_contract_id = "0" * 32  # 合法的 uuid4 hex 形状，但从未被创建过

    response = client.post(f"/contracts/{fake_contract_id}/parse")

    assert response.status_code == 404


def test_parse_registered_but_unimplemented_format_returns_415(client):
    """要求 5：pdf 当前在 DocumentParser 里是"已注册但未实现"（PdfParser 占位类），
    对调用方来说就是"这个格式解析不了"，应该得到 4xx，而不是把 NotImplementedError
    直接暴露成 500。
    """
    contract_id = _upload(client, filename="劳动合同.pdf", content=b"%PDF-1.4 fake pdf bytes")

    response = client.post(f"/contracts/{contract_id}/parse")

    assert response.status_code == 415


def test_parse_genuinely_unregistered_extension_returns_415(client):
    """要求 5 的另一种情况：扩展名连占位解析器都没有注册（DocumentParser 里
    抛的是 UnsupportedFormatError，不是 NotImplementedError），同样应该是 4xx。
    """
    contract_id = _upload(client, filename="劳动合同.xyz", content=b"some bytes")

    response = client.post(f"/contracts/{contract_id}/parse")

    assert response.status_code == 415


# ---------------------------------------------------------------------------
# GET /contracts/{contract_id}/clauses
# ---------------------------------------------------------------------------


def test_get_clauses_returns_200_with_correct_clause_list(client):
    """要求 1：已完成切分的合同 → 200 + 正确的 Clause 列表。"""
    contract_id = _upload(client)
    client.post(f"/contracts/{contract_id}/parse")  # 先切分，/clauses 只负责读回

    response = client.get(f"/contracts/{contract_id}/clauses")

    assert response.status_code == 200
    clauses = response.json()
    assert len(clauses) == 3
    assert all(c["contract_id"] == contract_id for c in clauses)
    assert clauses[0]["original_text"].startswith("第一条 试用期工资")


def test_get_clauses_matches_contract_manager_get_clauses(client, tmp_path):
    """要求 2：接口返回的内容必须和直接调用 ContractManager.get_clauses() 一致
    （证明路由没有自己重新读取/解析 clauses.json，也没有悄悄改动数据）。
    """
    contract_id = _upload(client)
    client.post(f"/contracts/{contract_id}/parse")

    response = client.get(f"/contracts/{contract_id}/clauses")

    direct = ContractManager(root_dir=tmp_path / "contracts").get_clauses(contract_id)
    assert response.json() == [c.model_dump(mode="json") for c in direct]


def test_get_clauses_unknown_contract_id_returns_404(client):
    """要求 3：不存在的 contract_id → 404。"""
    fake_contract_id = "1" * 32

    response = client.get(f"/contracts/{fake_contract_id}/clauses")

    assert response.status_code == 404


def test_get_clauses_before_parse_returns_reasonable_error(client):
    """要求 4：合同存在，但还没调用过 /parse（没有 clauses.json）→ 合理的 HTTP 错误。

    ContractManager.get_clauses 对"合同不存在"和"尚未切分"抛的是同一个
    ContractNotFoundError，所以这里同样是 404——这不是遗漏，而是如实反映
    现有异常类型，见 api/routes/contracts.py 里 get_contract_clauses 的说明。
    """
    contract_id = _upload(client)  # 只上传，不调用 /parse

    response = client.get(f"/contracts/{contract_id}/clauses")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /contracts/{contract_id}/review
# ---------------------------------------------------------------------------


def test_review_returns_200_with_review_report_structure(review_client):
    """要求 1 + 2：正常 review → 200，返回结构是 ReviewReport
    （contract_id / results / failed_clauses / summary / overall_risk_level）。

    直接上传后调用 /review，不先调用 /parse——用来顺带验证 run_review 内部的
    Contract Loading 节点会自己完成解析 + 切分，路由不需要替它多做这一步。
    """
    client, _ = review_client
    contract_id = _upload(client)

    response = client.post(f"/contracts/{contract_id}/review")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_id"] == contract_id
    assert "results" in body
    assert "failed_clauses" in body
    assert "summary" in body  # ReviewReport 的 computed_field
    assert "overall_risk_level" in body


def test_review_results_and_failed_clauses_come_from_run_review(review_client):
    """要求 4：results / failed_clauses 正确来自 run_review 的最终 state，
    不是路由自己拼出来的。
    """
    client, fake_reviewer = review_client
    contract_id = _upload(client)

    response = client.post(f"/contracts/{contract_id}/review")
    body = response.json()

    assert body["failed_clauses"] == []  # 测试替身的 review() 不会抛 ReviewError

    llm_results = [r for r in body["results"] if r["source"] == "llm"]
    assert len(llm_results) == 3  # 样例合同有 3 条 Clause，fake reviewer 逐条产出一个 llm 结果
    assert {r["clause_id"] for r in llm_results} == set(fake_reviewer.reviewed_clause_ids)


def test_review_calls_injected_reviewer_not_api_own_logic(review_client):
    """要求 6：验证 API 没有自己重写审查逻辑——审查结果确实是通过
    Depends(get_reviewer) 注入进来的 reviewer.review() 逐条产出的。
    """
    client, fake_reviewer = review_client
    contract_id = _upload(client)

    response = client.post(f"/contracts/{contract_id}/review")

    assert response.status_code == 200
    assert len(fake_reviewer.reviewed_clause_ids) == 3
    assert len(set(fake_reviewer.reviewed_clause_ids)) == 3  # 每条 clause 只被审查一次


def test_review_unknown_contract_id_returns_404(review_client):
    """要求 5：不存在的 contract_id → 合理 HTTP 错误。

    Contract Loading 节点内部调用的就是 parse_contract，抛出的仍然是
    ContractNotFoundError，映射方式和 POST /parse 完全一致。
    """
    client, _ = review_client
    fake_contract_id = "2" * 32

    response = client.post(f"/contracts/{fake_contract_id}/review")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /contracts/{contract_id}
# ---------------------------------------------------------------------------


def test_get_contract_returns_200_with_uploaded_status(client):
    """上传合同后 GET → 200，字段正确，状态是 uploaded（刚创建、还没 /parse）。"""
    content = "劳动合同条款内容".encode("utf-8")
    files = {"file": ("劳动合同.txt", io.BytesIO(content), "text/plain")}
    upload_response = client.post("/contracts", files=files)
    contract_id = upload_response.json()["contract_id"]

    response = client.get(f"/contracts/{contract_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ContractStatus.UPLOADED.value
    assert body["filename"] == "劳动合同.txt"
    assert body["sha256"] == upload_response.json()["sha256"]
    assert body["size_bytes"] == len(content)


def test_get_contract_unknown_contract_id_returns_404(client):
    """不存在的 contract_id → 404。"""
    fake_contract_id = "3" * 32

    response = client.get(f"/contracts/{fake_contract_id}")

    assert response.status_code == 404


def test_get_contract_status_advances_to_split_after_parse(client):
    """上传 + 调用 /parse 之后再 GET，状态应该推进到 split
    （ContractManager.save_clauses 会把状态从 uploaded 推进到 split）。
    """
    contract_id = _upload(client)
    client.post(f"/contracts/{contract_id}/parse")

    response = client.get(f"/contracts/{contract_id}")

    assert response.status_code == 200
    assert response.json()["status"] == ContractStatus.SPLIT.value


# ---------------------------------------------------------------------------
# GET /contracts（合同库）
# ---------------------------------------------------------------------------


def test_list_contracts_returns_empty_list_when_none_uploaded(client):
    """还没有任何合同时，GET /contracts 返回空列表，而不是 404 或 500。"""
    response = client.get("/contracts")

    assert response.status_code == 200
    assert response.json() == []


def test_list_contracts_includes_all_uploaded_contracts(client):
    """上传两份合同后，GET /contracts 应该都能看到，且字段与合同库要求一致
    （contract_id / filename / status / created_at / updated_at）。
    """
    id_a = _upload(client, filename="合同A.txt")
    id_b = _upload(client, filename="合同B.txt")

    response = client.get("/contracts")

    assert response.status_code == 200
    body = response.json()
    assert {c["contract_id"] for c in body} == {id_a, id_b}
    for item in body:
        assert set(item.keys()) >= {"contract_id", "filename", "status", "created_at", "updated_at"}


def test_list_contracts_excludes_v2_host_contract(client, tmp_path):
    """阶段 1：生成 V2 用的是和用户上传完全相同的 create_contract 入口，
    但 GET /contracts（合同库）必须把它排除——这里不走完整的批次/修改/生成
    流程（那是另一整套需要真实 LLM 的能力，不属于本次改动范围），而是直接
    用 ContractManager.save_version 构造一条"contract_b 是 contract_a 的
    V2 宿主"的版本记录，验证路由确实调用了 exclude_version_hosts=True。
    """
    id_a = _upload(client, filename="原始合同.txt")
    id_b = _upload(client, filename="这其实是V2的宿主.txt")

    manager = ContractManager(root_dir=tmp_path / "contracts")
    manager.save_version(
        ContractVersion(
            version_id=f"{id_a}_v2",
            contract_id=id_a,
            version_number="v2",
            linked_contract_id=id_b,
        )
    )

    response = client.get("/contracts")

    assert response.status_code == 200
    assert [c["contract_id"] for c in response.json()] == [id_a]

    # 排除只影响"合同库"这一个列表，B 自己仍然是一份完整、可以正常读取的
    # Contract——没有被删除、没有被改动。
    assert client.get(f"/contracts/{id_b}").status_code == 200


# ---------------------------------------------------------------------------
# GET /contracts/{contract_id}/text
# ---------------------------------------------------------------------------


def test_get_text_returns_full_parsed_text_after_parsing(client):
    """解析过的合同，GET /text 应该原样返回 parsed_text.txt 的完整内容。"""
    contract_id = _upload(client)
    client.post(f"/contracts/{contract_id}/parse")

    response = client.get(f"/contracts/{contract_id}/text")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_id"] == contract_id
    assert body["text"] == _SAMPLE_CONTRACT_TEXT


def test_get_text_for_unknown_contract_returns_404(client):
    """合同根本不存在时，GET /text 应该是 404，错误信息指向"合同不存在"。"""
    fake_contract_id = "6" * 32
    response = client.get(f"/contracts/{fake_contract_id}/text")

    assert response.status_code == 404
    assert "不存在" in response.json()["detail"]


def test_get_text_before_parsing_returns_404(client):
    """合同存在但还没调用过 /parse 时，GET /text 应该是 404，错误信息指向
    "尚未解析"——和"合同不存在"用不同的提示文案，方便调用方判断。
    """
    contract_id = _upload(client)

    response = client.get(f"/contracts/{contract_id}/text")

    assert response.status_code == 404
    assert "尚未解析" in response.json()["detail"]


def test_get_text_works_for_any_contract_id_not_only_v2(client):
    """接口是通用的原文读取接口，不区分 V1/V2：直接用 V1 自己的 contract_id
    也能正常读取（前端"V2 原文"标签页会传 linked_contract_id，但后端本身
    不对 contract_id 的"身份"做任何特殊判断）。
    """
    contract_id = _upload(client, filename="随便一份合同.txt")
    client.post(f"/contracts/{contract_id}/parse")

    response = client.get(f"/contracts/{contract_id}/text")

    assert response.status_code == 200
    assert response.json()["text"] == _SAMPLE_CONTRACT_TEXT


def test_get_text_does_not_create_any_review_record(review_client):
    """查看原文是纯读取操作：调用 GET /text 前后，这份合同的审查记录列表
    必须完全不变（不会意外触发审查流程、不会创建 ReviewRecord）。
    """
    client, _ = review_client
    contract_id = _upload(client)
    client.post(f"/contracts/{contract_id}/parse")

    before = client.get(f"/contracts/{contract_id}/reviews").json()
    assert before == []

    text_response = client.get(f"/contracts/{contract_id}/text")
    assert text_response.status_code == 200

    after = client.get(f"/contracts/{contract_id}/reviews").json()
    assert after == []


# ---------------------------------------------------------------------------
# GET /contracts/{contract_id}/review、GET /contracts/{contract_id}/reviews
# ---------------------------------------------------------------------------


def test_get_latest_review_before_any_review_returns_404(client):
    """合同存在但从未审查过时，GET /review 应该是 404，不是 500 或空对象。"""
    contract_id = _upload(client)

    response = client.get(f"/contracts/{contract_id}/review")

    assert response.status_code == 404


def test_review_result_is_persisted_and_retrievable(review_client):
    """要求：POST /review 执行完之后，结果必须能通过 GET /review 重新取到
    （不是只在这一次 HTTP 响应里出现一次，之后就没了）。
    """
    client, _ = review_client
    contract_id = _upload(client)

    post_response = client.post(f"/contracts/{contract_id}/review")
    assert post_response.status_code == 200
    posted_report = post_response.json()

    get_response = client.get(f"/contracts/{contract_id}/review")
    assert get_response.status_code == 200
    record = get_response.json()

    assert record["contract_id"] == contract_id
    assert record["contract_version"] == "v1"
    assert record["review_id"] == "v1_001"
    assert record["report"]["contract_id"] == contract_id
    assert record["report"]["results"] == posted_report["results"]
    assert record["report"]["summary"] == posted_report["summary"]


def test_review_after_save_advances_contract_status_to_reviewed(review_client):
    """审查结果持久化之后，合同状态应该推进到 reviewed（GET /contracts/{id} 可见）。"""
    client, _ = review_client
    contract_id = _upload(client)

    client.post(f"/contracts/{contract_id}/review")

    response = client.get(f"/contracts/{contract_id}")
    assert response.json()["status"] == ContractStatus.REVIEWED.value


def test_repeated_review_does_not_overwrite_history(review_client):
    """要求：重新审查不能覆盖之前的审查记录——两次 POST /review 之后，
    GET /reviews 必须能看到两条独立的历史记录。
    """
    client, _ = review_client
    contract_id = _upload(client)

    client.post(f"/contracts/{contract_id}/review")
    client.post(f"/contracts/{contract_id}/review")

    response = client.get(f"/contracts/{contract_id}/reviews")

    assert response.status_code == 200
    records = response.json()
    assert len(records) == 2
    assert [r["review_id"] for r in records] == ["v1_001", "v1_002"]


def test_list_reviews_unknown_contract_id_returns_404(client):
    """不存在的 contract_id → GET /reviews 应该是 404。"""
    fake_contract_id = "4" * 32

    response = client.get(f"/contracts/{fake_contract_id}/reviews")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /contracts/{contract_id}/modification-batches、
# POST /contracts/{contract_id}/modification-tasks、GET .../modification-tasks
#
# 创建 ModificationTask 现在要求显式携带一个已存在的 batch_id（见
# ModificationTaskCreate 的字段说明），而 batch 本身又要求一个真实存在的
# source_review_id——所以这里的前置步骤从"上传 + parse"变成"上传 + review"
# （review 本身内部会先完成 parse + split），用 review_client 而不是 client，
# 这样才能拿到一个真实的 review_id 去开一个批次。original_text 不再是
# 请求体字段：它现在由服务端用 contract_id + clause_id 从 ContractManager
# 查出真实原文，所以这里也不再在 payload 里传它。
# ---------------------------------------------------------------------------


def _create_batch(client, contract_id: str) -> str:
    """先跑一次 review 拿到真实 review_id，再开一个批次，返回 batch_id。"""
    client.post(f"/contracts/{contract_id}/review")
    review_id = client.get(f"/contracts/{contract_id}/review").json()["review_id"]
    response = client.post(
        f"/contracts/{contract_id}/modification-batches",
        json={"source_review_id": review_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["batch_id"]


def test_create_modification_task_returns_201_with_pending_status(review_client):
    """律师提交修改意见后，应该得到 201 + 一条 status 为 pending 的任务。"""
    client, _ = review_client
    contract_id = _upload(client)
    batch_id = _create_batch(client, contract_id)

    payload = {
        "batch_id": batch_id,
        "clause_id": "clause_001",
        "lawyer_instruction": "建议将试用期工资比例调整为不低于百分之八十。",
    }
    response = client.post(f"/contracts/{contract_id}/modification-tasks", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["contract_id"] == contract_id
    assert body["batch_id"] == batch_id
    # ModificationTask 的响应字段在“合同修改闭环”阶段做了改名/改类型：
    # clause_id -> target_clause_id；lawyer_instruction（单条）-> lawyer_instructions（列表，累计历史）。
    # 请求体（ModificationTaskCreate）的字段名保持不变，这里断言的是响应体。
    assert body["target_clause_id"] == "clause_001"
    assert body["lawyer_instructions"] == [payload["lawyer_instruction"]]
    assert body["status"] == "pending"
    assert body["task_id"] == "task_001"
    # original_text 必须是服务端从 ContractManager 查出来的真实条款原文，
    # 不是（本次请求体里根本不存在的）客户端传入值。
    assert "试用期" in body["original_text"]
    # 任务创建时必须冻结对应 Review 的风险快照。
    assert body["source_review_snapshot"] is not None


def test_list_modification_tasks_returns_created_tasks_in_order(review_client):
    """创建两条任务后，GET 应该按创建顺序都能看到（不覆盖、不丢失）。"""
    client, _ = review_client
    contract_id = _upload(client)
    batch_id = _create_batch(client, contract_id)

    client.post(
        f"/contracts/{contract_id}/modification-tasks",
        json={"batch_id": batch_id, "clause_id": "clause_001", "lawyer_instruction": "意见一"},
    )
    client.post(
        f"/contracts/{contract_id}/modification-tasks",
        json={"batch_id": batch_id, "clause_id": "clause_002", "lawyer_instruction": "意见二"},
    )

    response = client.get(f"/contracts/{contract_id}/modification-tasks")

    assert response.status_code == 200
    tasks = response.json()
    assert [t["task_id"] for t in tasks] == ["task_001", "task_002"]


def test_list_modification_tasks_empty_when_none_created(client):
    """还没有创建任何修改任务时，返回空列表，而不是 404。"""
    contract_id = _upload(client)

    response = client.get(f"/contracts/{contract_id}/modification-tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_create_modification_task_unknown_contract_id_returns_404(client):
    """不存在的 contract_id → 创建修改任务应该是 404，而不是把它悄悄建在磁盘上。

    batch_id 这里必然对应不到任何真实批次，但要验证的是"合同不存在"这个
    更靠前的检查先触发，所以传一个格式合法但不存在的 batch_id 占位即可。
    """
    fake_contract_id = "5" * 32

    response = client.post(
        f"/contracts/{fake_contract_id}/modification-tasks",
        json={"batch_id": "fake_batch", "clause_id": "clause_001", "lawyer_instruction": "意见"},
    )

    assert response.status_code == 404


def test_create_modification_task_missing_field_returns_422(review_client):
    """请求体缺少必填字段（例如缺少 lawyer_instruction）→ FastAPI 自带的 422 校验。"""
    client, _ = review_client
    contract_id = _upload(client)
    batch_id = _create_batch(client, contract_id)

    response = client.post(
        f"/contracts/{contract_id}/modification-tasks",
        json={"batch_id": batch_id, "clause_id": "clause_001"},
    )

    assert response.status_code == 422
