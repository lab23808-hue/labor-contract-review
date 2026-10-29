"""scripts/ 下各真实环境脚本共用的小工具。

只服务于 scripts/，不属于任何生产包，不会被生产代码依赖。
三个函数的共同原则：环境有问题（模型加载失败、知识库为空、缺 API Key）就清晰地报告并
退出，绝不自动换成假实现或悄悄兜底——真实验证脚本的意义就是暴露真实环境的问题。
"""

import sys

from infra.llm import build_deepseek_client
from retrieval import DenseBackend, build_embedder


def load_real_embedder_or_exit():
    """构造真实的 BGE-M3 embedding 函数，并主动探测一次，尽早暴露加载失败。

    HuggingFaceEmbeddings 的模型下载是懒加载的：构造实例本身不会报错，
    真正下载/加载模型是在第一次调用 embed_query / embed_documents 时才发生。
    这里在使用前先做一次探测调用，把下载失败暴露在脚本一开始，
    而不是让它在写入知识库写到一半时才报错。

    加载失败时只报告这是环境问题并退出，绝不会自动换成假 embedding——
    真实检索效果必须用真实模型验证，用假数据掩盖失败没有意义。
    """
    embedder = build_embedder()
    try:
        embedder.embed_query("环境自检")
    except Exception as exc:  # noqa: BLE001 - 这里就是要兜住任何加载失败的原因，原样报告给用户
        print("=" * 60, file=sys.stderr)
        print("!! 无法加载真实的 BGE-M3 模型，这是环境问题，不会自动切换成伪 embedding !!", file=sys.stderr)
        print(f"   错误类型：{type(exc).__name__}", file=sys.stderr)
        print(f"   错误信息：{exc}", file=sys.stderr)
        print("   请检查：", file=sys.stderr)
        print("     1) 是否已执行 pip install -r requirements.txt（含 sentence-transformers）；", file=sys.stderr)
        print("     2) 当前网络是否能访问 huggingface.co（国内可配置 HF_ENDPOINT 镜像）；", file=sys.stderr)
        print("     3) 磁盘空间是否足够（BGE-M3 权重约 2GB）。", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.exit(1)
    return embedder


def open_knowledge_base_or_exit(embedder):
    """打开 data/index/chroma 里正式的知识库；如果是空的，提示先初始化并退出。

    只负责"打开 + 检查非空"，不写入任何数据。
    """
    kb = DenseBackend(embedder)
    if kb.count() == 0:
        raise SystemExit(
            f'知识库是空的（collection="{kb.collection_name}"，目录={kb.persist_directory}）。'
            "请先运行 python scripts/build_knowledge_base.py 完成初始化。"
        )
    return kb


def build_real_llm_client_or_exit():
    """构造真实的 DeepSeek 客户端；缺 API Key 等配置问题原样报告并退出。"""
    try:
        return build_deepseek_client()
    except Exception as exc:  # noqa: BLE001 - 环境问题原样报告，不做任何兜底
        raise SystemExit(f"无法构造 DeepSeek 客户端：{exc}") from exc
