"""项目级默认配置：只集中"真正跨模块共享的默认值"。

原则：
- 只放常量。不放配置类、不做读取/校验逻辑、不引入配置注册机制。
- 各模块仍然可以通过构造函数参数覆盖这里的默认值（测试就是这样指定临时目录的）。
- API Key 等密钥不放在这里，继续通过环境变量 / .env 读取（见 infra/llm/client.py）。
- 本模块不依赖项目里的任何其他包，只用标准库。
"""

from pathlib import Path
import os

# ---------------------------------------------------------------- 路径
# 基于本文件位置推导，不依赖运行时的当前工作目录。
# src/config/settings.py → parents[2] = 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CONTRACTS_DIR = DATA_DIR / "runtime" / "contracts"  # 用户合同运行时数据
KNOWLEDGE_DIR = DATA_DIR / "knowledge"  # 法律知识库原始文本（*.txt，版本可控）
CHROMA_DIR = DATA_DIR / "index" / "chroma"  # Chroma 持久化索引（派生数据）

# ---------------------------------------------------------------- RAG
CHROMA_COLLECTION_NAME = "legal_knowledge"
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
RETRIEVAL_TOP_K = 5  # 每次检索返回的法律依据条数

# 检索策略，只能是 "bm25"、"dense" 或 "hybrid"：
#   "bm25"（默认）：字符二元组(char_bigram)分词的 BM25Okapi（k1=1.5, b=0.75），
#       服务启动时从 KNOWLEDGE_DIR 下的正式知识库文本构建纯内存索引，不依赖
#       Chroma/BGE-M3，见 retrieval/backends/lexical/index.py。
#   "dense"：原有的 BGE-M3 向量检索（Chroma），作为可配置的备选方案保留，
#       底层代码完全未改动——改成这个值、重启服务即可一比一恢复到本次 BM25
#       正式接入之前的检索行为（这是最简单的回滚方式之一，另见
# 非法取值在 api/dependencies.py::build_app_state() 启动时直接报错，不会
# 静默退化到某一个默认策略。
RETRIEVAL_STRATEGY = os.getenv("RETRIEVAL_STRATEGY", "bm25")

# ---------------------------------------------------------------- 文本切分
# 合同条款切分（domain/document/）和法律知识切分（retrieval/knowledge_loader.py）是两个互相独立的模块，
# 目前恰好取值相同，但分开命名：以后调其中一个，不应该悄悄影响另一个。
# 500 / 50 的取值理由见 domain/document/splitter.py 的类文档。
CLAUSE_CHUNK_SIZE = 500
CLAUSE_CHUNK_OVERLAP = 50
KNOWLEDGE_CHUNK_SIZE = 500
KNOWLEDGE_CHUNK_OVERLAP = 50

# ---------------------------------------------------------------- LLM
# 默认模型名。可以用环境变量 DEEPSEEK_MODEL 覆盖（见 infra/llm/client.py）。
# 注意：deepseek-chat / deepseek-reasoner 这两个旧模型名已于 2026-07-24 下线。
# 当前（2026-09）有效的模型名：
#   deepseek-flash    通用/日常任务，速度快、成本低（本默认值）
#   deepseek-v4-pro   复杂推理任务
# DeepSeek 的模型命名变动比较频繁，使用前建议在 .env 里显式配置成官方文档
# https://api-docs.deepseek.com 当前列出的名称，不要只依赖这个默认值。
LLM_MODEL_NAME = "deepseek-flash"

# 单次 LLM 请求的超时时间（秒）
LLM_TIMEOUT_SECONDS = 60
