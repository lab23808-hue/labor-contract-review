"""FastAPI 依赖注入：应用启动时把当前业务需要的重对象构造一次，
请求期间通过 Depends 从同一份实例里取用，不重复构造。

本文件只负责"接线"——调用已有业务模块（infra / retrieval / domain / app）
各自的构造函数，把结果的生命周期交给 FastAPI 的 lifespan 管理。
本文件不重新实现、也不改变任何业务逻辑；ContractManager、RAG 检索、
LLM 调用、RuleChecker 的行为完全由各自的模块决定。

不手写 Singleton 类：FastAPI 自带的三件套已经够用——
    lifespan   决定"什么时候构造、什么时候释放"
    app.state  决定"构造好的对象存在哪里"
    Depends    决定"路由怎么从请求里把对象取出来"
额外包一层 Singleton 只是重复造轮子，还会让"何时初始化"变得不透明。
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, Union

from fastapi import Depends, FastAPI, Request
from langchain_core.embeddings import Embeddings

from domain.agents.modification_agent import ModificationAgent
from domain.agents.review_agent import ClauseReviewer
from app.contract_service import ContractApplicationService
from app.diff_service import DiffApplicationService
from app.review_service import ReviewApplicationService
from app.v2_generation_service import V2GenerationService
from config import settings
from infra.storage import ContractManager
from infra.llm.client import OpenAICompatibleClient, build_deepseek_client
from domain.modification.service import ModificationService
from retrieval.backends.dense import DenseBackend
from retrieval.backends.hybrid import HybridBackend
from retrieval.backends.lexical import BM25Backend
from retrieval.embedding import build_embedder
from retrieval.knowledge_loader import KnowledgeLoader
from retrieval.retriever import LegalKnowledgeRetriever
from domain.rules import RuleChecker


@dataclass
class AppState:
    """应用启动时构造一次、请求期间共享的重对象集合。

    只是一个数据容器，不包含任何业务逻辑——真正的行为仍然全部在
    ContractManager / LegalKnowledgeRetriever / ClauseReviewer / RuleChecker
    自己身上，这里只是把它们放在一起、方便通过 app.state 传递。

    embedder / knowledge_base 改成 Optional（2026-10-12 BM25 正式接入）：
    settings.RETRIEVAL_STRATEGY="bm25" 时不初始化 Chroma/BGE-M3，这两个字段
    就是 None——没有任何路由直接依赖 get_embedder/get_knowledge_base（已检查
    api/routes/ 下所有路由，都只经过 get_retriever/get_reviewer 间接使用检索
    能力），所以这里允许它们为空不会破坏现有业务链路；retriever 本身永远不为
    None，是唯一对外统一暴露的检索入口。
    """

    contract_manager: ContractManager
    embedder: Optional[Embeddings]
    knowledge_base: Optional[Union[DenseBackend, HybridBackend]]
    retriever: LegalKnowledgeRetriever
    llm_client: OpenAICompatibleClient
    reviewer: ClauseReviewer
    rule_checker: RuleChecker
    # 注意：这里只存 ModificationAgent（只包着 llm_client，本身不持有任何
    # ContractManager 引用），不存 ModificationService——ModificationService
    # 必须在每次请求时用"当前这次请求实际拿到的 ContractManager"现场组装
    # （见下面 get_modification_service），否则它内部会永远绑死在
    # build_app_state() 构造时那一个 ContractManager 实例上，测试用
    # app.dependency_overrides[get_contract_manager] 换成指向 tmp_path 的
    # 实例时，ModificationService 会完全感知不到、继续用生产数据目录——
    # 这正是曾经出现过的一个真实 bug。
    modification_agent: ModificationAgent


def build_app_state() -> AppState:
    """真正构造所有重对象，并把它们按现有业务模块要求的方式组装起来。

    拆成独立函数（而不是直接写在 lifespan 里）是为了方便测试：
    测试可以直接调用 build_app_state() 断言组装是否正确，也可以整体
    monkeypatch 掉它，而不需要启动一个真实的 FastAPI 应用。

    fail fast：任何一步失败（缺 API Key、模型加载失败、Chroma 打不开等、
    BM25 索引构建失败等）都直接把异常抛出去，不在这里吞掉或降级——宁可应用
    启动不起来，也不要带着一个坏掉的 embedder / LLM client / 检索索引对外
    提供服务。

    检索后端按 settings.RETRIEVAL_STRATEGY 二选一地初始化（2026-10-12 BM25
    正式接入新增）：
        "bm25"（默认）：不加载 BGE-M3、不打开 Chroma——只读取 KNOWLEDGE_DIR
            下的正式知识库文本，复用 KnowledgeLoader 的"读文件→按条切分"逻辑
            （与写入 Chroma 时完全同一套代码路径，不是另起一套知识库读取
            流程）构建纯内存 BM25 索引。embedder/knowledge_base 留空（None），
            因为 BM25 路径本来就不需要它们，没理由为了"可能用到"而付出加载
            BGE-M3 的真实启动耗时和内存/显存代价——这是本次接入明确要求的
            "按配置选择性初始化"。
        "dense"：逐字沿用原有流程，不做任何改动，Dense 的真实向量检索能力
            和现有持久化 Chroma 索引完全保留。
    两条分支互斥：永远只构造当前策略实际需要的那一套重对象，不会"反正都
    建一遍再选用哪个"。
    """
    contract_manager = ContractManager()

    strategy = settings.RETRIEVAL_STRATEGY
    if strategy == "bm25":
        embedder = None
        knowledge_base = None
        # knowledge_base=None：KnowledgeLoader.load_directory()/load_file()/
        # split_text() 从不触碰 self.knowledge_base，只有 index()/
        # load_and_index_*() 才会用到它；BM25 路径不调用那些写入方法，这里
        # 传 None 是安全的。类型标注上仍要求一个 VectorSink/DenseBackend——这是
        # 已知的、刻意不去改动 retrieval/knowledge_loader.py 而接受的小瑕疵（把
        # "读取/切分"方法改成不依赖 knowledge_base 参数的 staticmethod/独立
        # 函数会更干净，留作后续知识树建议，不在本轮改动范围内）。
        evidences = KnowledgeLoader(knowledge_base=None).load_directory(settings.KNOWLEDGE_DIR)
        bm25_index = BM25Backend(evidences)  # 校验失败在这里直接抛 BM25IndexBuildError，不吞不降级
        retriever = LegalKnowledgeRetriever(knowledge_base=bm25_index)
    elif strategy == "dense":
        embedder = build_embedder()  # 加载 BGE-M3，只在这里做一次
        knowledge_base = DenseBackend(embedding_function=embedder)
        expected = KnowledgeLoader(None).count_evidences(settings.KNOWLEDGE_DIR)
        actual = knowledge_base.count()
        if actual != expected:
            raise RuntimeError(
                f"Dense 索引与知识库不一致：Chroma count={actual}，"
                f"知识库 Evidence 数={expected}（目录 {settings.KNOWLEDGE_DIR}）"
            )
        retriever = LegalKnowledgeRetriever(knowledge_base=knowledge_base)
    elif strategy == "hybrid":
        embedder = build_embedder()
        dense = DenseBackend(embedding_function=embedder)
        expected = KnowledgeLoader(None).count_evidences(settings.KNOWLEDGE_DIR)
        actual = dense.count()
        if actual != expected:
            raise RuntimeError(
                f"Hybrid 的 Dense 索引与知识库不一致：Chroma count={actual}，"
                f"知识库 Evidence 数={expected}（目录 {settings.KNOWLEDGE_DIR}）"
            )
        evidences = KnowledgeLoader(None).load_directory(settings.KNOWLEDGE_DIR)
        knowledge_base = HybridBackend(dense=dense, lexical=BM25Backend(evidences))
        retriever = LegalKnowledgeRetriever(knowledge_base=knowledge_base)
    else:
        raise ValueError(
            f"settings.RETRIEVAL_STRATEGY 取值非法：{strategy!r}，只能是 'bm25'、'dense' 或 'hybrid'"
        )

    llm_client = build_deepseek_client()  # 读 .env 里的 DEEPSEEK_API_KEY，只在这里做一次

    reviewer = ClauseReviewer(retriever=retriever, llm_client=llm_client)
    rule_checker = RuleChecker()

    modification_agent = ModificationAgent(llm_client=llm_client)

    return AppState(
        contract_manager=contract_manager,
        embedder=embedder,
        knowledge_base=knowledge_base,
        retriever=retriever,
        llm_client=llm_client,
        reviewer=reviewer,
        rule_checker=rule_checker,
        modification_agent=modification_agent,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时调用一次 build_app_state()，挂在 app.state 上供所有请求复用。

    当前所有重对象都不需要显式关闭：ContractManager 只是路径计算，
    Chroma 是本地文件持久化、没有需要手动断开的连接，OpenAI SDK 的
    客户端也不持有需要手动释放的资源。如果以后引入需要显式关闭的
    资源（例如连接池），在 yield 之后补充清理逻辑即可。
    """
    app.state.app_state = build_app_state()
    yield


def get_app_state(request: Request) -> AppState:
    """从当前请求里取出启动时构造好的 AppState。

    这是所有具体依赖函数的共同入口：路由不直接依赖 get_app_state，
    而是依赖下面这些按对象拆开的函数，避免每个路由都要自己再从
    AppState 里挑一次需要的字段。
    """
    return request.app.state.app_state


def get_contract_manager(request: Request) -> ContractManager:
    return get_app_state(request).contract_manager


def get_embedder(request: Request) -> Optional[Embeddings]:
    """RETRIEVAL_STRATEGY="bm25" 时返回 None（没有任何路由依赖这个函数，
    见 AppState 的字段说明）。"""
    return get_app_state(request).embedder


def get_knowledge_base(request: Request) -> Optional[Union[DenseBackend, HybridBackend]]:
    """RETRIEVAL_STRATEGY="bm25" 时返回 None（没有任何路由依赖这个函数，
    见 AppState 的字段说明）。"""
    return get_app_state(request).knowledge_base


def get_retriever(request: Request) -> LegalKnowledgeRetriever:
    return get_app_state(request).retriever


def get_llm_client(request: Request) -> OpenAICompatibleClient:
    return get_app_state(request).llm_client


def get_reviewer(request: Request) -> ClauseReviewer:
    return get_app_state(request).reviewer


def get_rule_checker(request: Request) -> RuleChecker:
    return get_app_state(request).rule_checker


def get_modification_agent(request: Request) -> ModificationAgent:
    return get_app_state(request).modification_agent


def get_contract_service(
    contract_manager: ContractManager = Depends(get_contract_manager),
) -> ContractApplicationService:
    return ContractApplicationService(contract_manager=contract_manager)


def get_modification_service(
    contract_manager: ContractManager = Depends(get_contract_manager),
    modification_agent: ModificationAgent = Depends(get_modification_agent),
    reviewer: ClauseReviewer = Depends(get_reviewer),
) -> ModificationService:
    """每次请求都现场组装 ModificationService，而不是从 AppState 里取一个
    启动时就固定好的单例。

    ModificationService 本身很轻（只是持有几个引用，没有需要复用的重初始化
    开销），现场组装的代价可以忽略；换来的好处是它会自动跟随
    Depends(get_contract_manager) 解析出的【当前这次请求实际使用的】
    ContractManager——不管这个 ContractManager 是 lifespan 启动时构造的那个，
    还是测试通过 app.dependency_overrides 换上去的那个，ModificationService
    看到的永远是同一个。ModificationAgent / ClauseReviewer 不受影响，因为它们
    只包着 llm_client / retriever，本身不持有 ContractManager 引用。

    reviewer 是 Modified Clause Risk Analyzer（Part D）需要的依赖——
    ModificationService.start_modification 在 Validator 通过后会复用这个
    ClauseReviewer 对候选文本重新跑一次独立审查。
    """
    return ModificationService(contract_manager=contract_manager, agent=modification_agent, reviewer=reviewer)


def get_v2_generation_service(
    contract_manager: ContractManager = Depends(get_contract_manager),
) -> V2GenerationService:
    """同上：现场组装，跟随当前请求实际使用的 ContractManager。"""
    return V2GenerationService(contract_manager=contract_manager)


def get_review_service(
    contract_manager: ContractManager = Depends(get_contract_manager),
    reviewer: ClauseReviewer = Depends(get_reviewer),
    rule_checker: RuleChecker = Depends(get_rule_checker),
) -> ReviewApplicationService:
    """每次请求现场组装 Review Application 服务，原因与 get_modification_service
    完全相同：必须跟随 Depends(get_contract_manager) 解析出的【当前这次请求
    实际使用的】ContractManager，不能绑死在 lifespan 启动时构造的那一个实例上
    （测试会用 app.dependency_overrides 换成指向 tmp_path 的实例）。
    """
    return ReviewApplicationService(
        contract_manager=contract_manager,
        reviewer=reviewer,
        rule_checker=rule_checker,
    )


def get_diff_service(
    contract_manager: ContractManager = Depends(get_contract_manager),
) -> DiffApplicationService:
    """同上：现场组装，跟随当前请求实际使用的 ContractManager。"""
    return DiffApplicationService(contract_manager=contract_manager)
