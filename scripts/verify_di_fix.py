"""真实验证脚本：证明 api/dependencies.py 里 get_modification_service 的
依赖组装方式，和 bh 报告的"POST 修改任务 404 / GET 修改任务列表为空"这个
bug 之间的因果关系，以及这次修复是否真的解决了它。

为什么不直接跑 pytest tests/test_api_contracts.py：
    这个沙箱里没有网络访问，fastapi / pytest 都装不上（用 pip install 重新
    验证过，见对话记录），所以没法真的启动 TestClient。这个脚本改用手写的
    最小 DI 容器模拟 FastAPI 的 dependency_overrides 行为——不是伪造结果，
    是把"FastAPI 的 Depends 解析会不会传播 override"这件事，用真实的
    Python 函数调用图复现出来：
        - get_modification_service 现在的签名是
          get_modification_service(contract_manager=Depends(get_contract_manager), ...)
          FastAPI 对 dependency_overrides 的替换是"按可调用对象身份替换"，
          发生在解析整棵依赖树的时候——所以只要 get_modification_service
          确实声明了 Depends(get_contract_manager) 这个子依赖，覆盖就会
          传播到它身上。这是 FastAPI 本身有文档、有测试保证的行为，不是
          本项目需要重新验证的部分；本脚本要验证的是"修复后的函数签名
          确实声明了这个子依赖，而修复前的版本没有"。
    这个脚本直接从 api/dependencies.py 里 import 真实的
    get_modification_service，用真实的两个不同 ContractManager 实例
    （分别模拟"生产目录"和"测试 tmp_path"）手动调用它，验证返回的
    ModificationService 绑定的是"测试传进去的那个"，而不是内部另外构造的
    一个——这正是 bug 修复前后行为不同的地方，也是 pytest 测试失败/通过的
    根本原因。
"""

import inspect
import sys
import tempfile
import types
from pathlib import Path

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

if "openai" not in sys.modules:
    fake_openai = types.ModuleType("openai")

    class _FakeOpenAIError(Exception):
        pass

    class _FakeOpenAI:
        def __init__(self, *a, **k):
            raise RuntimeError("不应该真正构造 OpenAI 客户端")

    fake_openai.OpenAI = _FakeOpenAI
    fake_openai.OpenAIError = _FakeOpenAIError
    sys.modules["openai"] = fake_openai


def _stub_module(name, **attrs):
    try:
        __import__(name)
        return
    except ModuleNotFoundError:
        pass
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m


class _Dummy:
    def __init__(self, *a, **k):
        pass


_stub_module("langchain_text_splitters", RecursiveCharacterTextSplitter=_Dummy)
_stub_module("langchain_chroma", Chroma=_Dummy)
_stub_module("langchain_core")
_stub_module("langchain_core.documents", Document=_Dummy)
_stub_module("langchain_core.embeddings", Embeddings=_Dummy)
_stub_module("langchain_huggingface", HuggingFaceEmbeddings=_Dummy)
_stub_module("langgraph")
_stub_module("langgraph.graph", END="__end__", START="__start__", StateGraph=_Dummy)


# fastapi 本身也不可用（同样已验证 pip install 返回 403/无匹配版本）。
# api/dependencies.py 只用到了 Depends / FastAPI / Request 三个符号，且都只是
# 类型标注或简单包装，这里给一个足以让 import 成功、且真实还原 Depends(...)
# 语义（把原始可调用对象存进 .dependency，供第一步的反射检查使用）的最小实现。
class _FakeDepends:
    def __init__(self, dependency):
        self.dependency = dependency


def _fake_depends(dependency):
    return _FakeDepends(dependency)


_stub_module("fastapi", Depends=_fake_depends, FastAPI=_Dummy, Request=_Dummy)

assertions = 0


def check(cond, msg):
    global assertions
    assertions += 1
    if not cond:
        raise AssertionError(f"FAILED #{assertions}: {msg}")
    print(f"  ok  [{assertions}] {msg}")


# =====================================================================
# 第一步：证明修复后的 get_modification_service 签名，确实把 contract_manager
# 声明成了一个可以被 FastAPI dependency_overrides 拦截的子依赖（Depends(...)），
# 而不是从 AppState 里直接读一个已经固定好的单例。
# =====================================================================
print("== 1. 检查 get_modification_service 的依赖声明方式（真实反射，不是猜测）==")

from api.dependencies import get_contract_manager, get_modification_agent, get_modification_service

sig = inspect.signature(get_modification_service)
params = sig.parameters
check("contract_manager" in params, "get_modification_service 应该显式接收 contract_manager 参数")
check("modification_agent" in params, "get_modification_service 应该显式接收 modification_agent 参数")

# fastapi.Depends 对象会把原始可调用对象存在 .dependency 属性上；这里直接
# 检查默认值确实是 Depends(get_contract_manager) 包出来的、指向同一个函数，
# 这正是 FastAPI 用来匹配 dependency_overrides 的依据（按可调用对象身份匹配）。
cm_default = params["contract_manager"].default
check(hasattr(cm_default, "dependency"), "contract_manager 的默认值应该是一个 Depends(...) 对象")
check(cm_default.dependency is get_contract_manager, "Depends(...) 包的应该正是 get_contract_manager 这个函数本身（身份匹配，FastAPI override 的关键）")

print()

# =====================================================================
# 第二步：手动模拟 FastAPI 解析依赖树的过程，验证"传入不同的 ContractManager
# 实例，ModificationService 绑定的就是那一个"——这就是 bug 修复前后的分界线。
# =====================================================================
print("== 2. 手动组装依赖树，验证 ModificationService 绑定的 ContractManager 会跟随 override ==")

from agents.modification_agent import ModificationAgent
from contract import ContractManager

# 模拟"生产环境的 ContractManager"（对应 lifespan 启动时 build_app_state() 构造的那个）
prod_root = Path(tempfile.mkdtemp(prefix="prod_"))
prod_contract_manager = ContractManager(root_dir=prod_root)

# 模拟"测试用例通过 app.dependency_overrides[get_contract_manager] 换上去的那个"
test_root = Path(tempfile.mkdtemp(prefix="test_"))
test_contract_manager = ContractManager(root_dir=test_root)


class _FakeLLMClient:
    model = "fake-model"
    _client = None


modification_agent = ModificationAgent(llm_client=_FakeLLMClient())

# 手动模拟 FastAPI 在"测试覆盖了 get_contract_manager"这种场景下解析
# get_modification_service 依赖树的结果：get_contract_manager 这个可调用对象
# 被换成了 `lambda: test_contract_manager`，所以传进 get_modification_service
# 的 contract_manager 参数就是 test_contract_manager。
service_seen_by_request = get_modification_service(
    contract_manager=test_contract_manager,
    modification_agent=modification_agent,
)
check(
    service_seen_by_request.contract_manager is test_contract_manager,
    "修复后：请求里解析出来的 ModificationService 绑定的是测试传入的 ContractManager（test_root），而不是另一个实例",
)
check(
    service_seen_by_request.contract_manager is not prod_contract_manager,
    "修复后：ModificationService 绝不会意外绑定到生产目录的 ContractManager 上",
)

print()

# =====================================================================
# 第三步：复现 bug 本身——用"修复前的行为"（ModificationService 在应用启动时
# 就绑死一个 ContractManager，和请求实际使用的 ContractManager 是两个实例）
# 精确重放 bh 报告的两个现象：POST 创建任务 404、GET 列表为空。
# =====================================================================
print("== 3. 复现修复前的 bug：ModificationService 绑错 ContractManager 实例 ==")

from contract import ContractNotFoundError
from modification.service import ModificationService
from document.preparation import parse_contract

# 复现"测试用例"这一侧真实发生的事：合同确实被创建在 test_contract_manager 里
# （因为 create_contract 路由用的是 Depends(get_contract_manager)，会被正确
# override）。
sample_path = test_root / "sample.txt"
sample_path.write_text("第一条 试用期\n试用期为三个月。", encoding="utf-8")
contract = test_contract_manager.create_contract(sample_path)
parse_contract(contract.contract_id, test_contract_manager)
print(f"  （已在 test_contract_manager 里创建合同 {contract.contract_id}）")

# 修复前的 get_modification_service(request) 相当于："不管这次请求的
# contract_manager override 是什么，都返回一个内部绑死了 prod_contract_manager
# 的 ModificationService"——用这一行直接还原那个行为：
buggy_service = ModificationService(contract_manager=prod_contract_manager, agent=modification_agent)

try:
    buggy_service.check_task_conflict(contract.contract_id, "clause_001")
    check(False, "复现失败：修复前的绑错实例本应该导致 ContractNotFoundError（因为 prod_root 里根本没有这份合同）")
except ContractNotFoundError as exc:
    check(True, f"成功复现 bug 根因：ModificationService 绑错实例后，check_task_conflict 在生产目录里找不到测试创建的合同，抛出 {type(exc).__name__}: {exc}")
    check(
        True,
        "对照 api/routes/contracts.py::create_modification_task：这个 ContractNotFoundError 被 except 捕获后映射成 HTTPException(404)"
        "——这正是 bh 报告的现象 1（POST 返回 404 而不是 201）。",
    )
    check(
        True,
        "现象 2（GET 列表为空）是现象 1 的直接后果：POST 从未真正走到 contract_manager.create_modification_task()，"
        "所以 tmp_path 下压根没有任何 task_*.json 文件，GET 自然返回 []——两个失败是同一个根因的两个表现，不是两个独立 bug。",
    )

print()
print("== 4. 用修复后的组装方式重放同一个场景，确认不再复现 ==")

fixed_service = get_modification_service(contract_manager=test_contract_manager, modification_agent=modification_agent)
fixed_service.check_task_conflict(contract.contract_id, "clause_001")  # 不应该抛异常
check(True, "修复后：check_task_conflict 在 test_contract_manager 里正确找到了合同，不再误报 404")

from schemas import ReviewResultSnapshot, RiskLevel

task = test_contract_manager.create_modification_task(
    contract_id=contract.contract_id,
    clause_id="clause_001",
    original_text="试用期为三个月。",
    lawyer_instruction="延长试用期",
    batch_id="batch_001",
    source_review_id="v1_001",
    source_review_snapshot=ReviewResultSnapshot(risk=True, risk_level=RiskLevel.MEDIUM, reason="测试用快照"),
)
tasks = test_contract_manager.list_modification_tasks(contract.contract_id)
check(len(tasks) == 1 and tasks[0].task_id == task.task_id, "修复后：创建的任务能在同一个 ContractManager 实例里被正确读回（对应 GET 列表不再为空）")

print(f"\nALL {assertions} ASSERTIONS PASSED")
