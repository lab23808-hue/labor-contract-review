"""P-24 修复验证：generate_v2 写临时文件时改用 newline=""，验证它确实
"完全关闭换行符转换"这个 Python io 语义，而不是猜测它有效。

重要的诚实说明（这条必须写进报告，不能隐瞒）：
    这次真实生产环境复现的问题，根源是 os.linesep 在不同平台不同
    （Linux/Mac 是 "\n"，Windows 是 "\r\n"），而 Path.write_text 默认
    (newline=None) 会把字符串里裸的 "\n" 替换成 os.linesep。本沙箱是
    Linux，os.linesep 恒为 "\n"，替换成它自己等于什么都没发生——
    也就是说，这个 bug 在 Linux 上天生无法被复现，不是"没测出来"，是
    这台机器的 os.linesep 让问题不成立。
    实测验证过：直接在 Python 里给 os.linesep 赋值成 "\r\n" 也【不会】
    改变 write_text 的实际写入行为——CPython 的 io 模块在文本模式写入时
    使用的是编译期/运行时平台的真实换行符，不是重新读取 os 模块这个可变
    属性，所以在这台 Linux 沙箱里，用"猴子补丁"伪造 Windows 环境来复现
    这个 bug 是做不到的。
    因此这里能做、也应该做的，是验证 newline="" 这个参数本身的语义
    ——根据 Python 官方文档，newline="" 表示"不做任何换行符转换，原样
    写出字符串里已有的字符"，这是平台无关的语义（不管在哪个操作系统上，
    newline="" 都关闭转换）。用一段刻意构造的、同时包含 "\n"、"\r\n"、
    孤立 "\r" 的字符串做写入/读回的逐字节往返测试，证明修复后的调用方式
    在任何平台上都不会引入任何转换——包括在本沙箱这个"问题原本就不会
    发生"的平台上也是如此。
    这不能替代在 bh 真实 Windows 环境上的最终确认，报告里必须明确写清楚
    这一点。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/mnt/user-data/outputs/labor_contract_review")

import types

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
    def __init__(self, *a, **k): pass

class _FakeOpenAIError(Exception):
    pass

_stub_module("openai", OpenAI=_Dummy, OpenAIError=_FakeOpenAIError)
_stub_module("dotenv", load_dotenv=lambda *a, **k: None)
_stub_module("langchain_text_splitters", RecursiveCharacterTextSplitter=_Dummy)
_stub_module("langchain_chroma", Chroma=_Dummy)
_stub_module("langchain_core")
_stub_module("langchain_core.documents", Document=_Dummy)
_stub_module("langchain_core.embeddings", Embeddings=_Dummy)
_stub_module("langchain_huggingface", HuggingFaceEmbeddings=_Dummy)
_stub_module("langgraph")
_stub_module("langgraph.graph", END="__end__", START="__start__", StateGraph=_Dummy)

assertions = 0
def check(cond, msg):
    global assertions
    assertions += 1
    if not cond:
        raise AssertionError(f"FAILED #{assertions}: {msg}")
    print(f"  ok  [{assertions}] {msg}")


print("== 1. newline=\"\" 应该对任意换行符组合都做到逐字节原样写入/读回 ==")

tricky_text = (
    "第二条 工作内容与工作地点\r\n"      # 已有的 CRLF（模拟 Windows 上传的原始文件）
    "乙方同意根据甲方工作安排。\n"        # 纯 LF
    "另起一段，孤立的 CR 结尾。\r"         # 孤立 CR（老式 Mac 换行，边界情况）
    "最后一行没有换行符"
)

tmp = Path(tempfile.mktemp(suffix=".txt"))
tmp.write_text(tricky_text, encoding="utf-8", newline="")
raw = tmp.read_bytes()
check(raw == tricky_text.encode("utf-8"), "newline=\"\" 写入后的原始字节应该和字符串编码后完全一致，不含任何换行符转换")

# 读回（模拟 generate_v2 之后 create_contract -> DocumentParser 的读取路径：
# 二进制读取 + 解码，不做换行转换）
read_back = raw.decode("utf-8")
check(read_back == tricky_text, "读回解码后应逐字节等于原始字符串（往返不失真）")
tmp.unlink(missing_ok=True)

print("\n== 2. 对照组：默认 newline=None 在本沙箱（Linux，os.linesep='\\n'）上不会暴露问题 ==")
import os
check(os.linesep == "\n", f"本沙箱是 Linux，os.linesep 应为 '\\n'，实际：{os.linesep!r}——这正是本 bug 在这里无法复现的原因")
tmp2 = Path(tempfile.mktemp(suffix=".txt"))
tmp2.write_text(tricky_text, encoding="utf-8")  # 默认 newline=None
raw2 = tmp2.read_bytes()
check(raw2 == tricky_text.encode("utf-8"), "在 os.linesep=='\\n' 的平台上，默认写法巧合地也不会损坏数据——这解释了为什么本沙箱之前的验证脚本测不出这个 bug，不代表默认写法本身是安全的")
tmp2.unlink(missing_ok=True)

print("\n== 3. 真实执行 V2 生成写入这一行代码，确认已经改成 newline=\"\" ==")
import inspect

# V2 生成逻辑已从 ModificationService.generate_v2 搬到
# application.v2_generation_service.V2GenerationService._do_generate
# （Part G，见 docs/DEVELOPMENT_LOG.md 对应日期的记录），newline="" 这一行
# 原样保留，只是换了个家，所以这里改成对新家做同样的源码检查。
import application.v2_generation_service as v2_gen_module
source = inspect.getsource(v2_gen_module.V2GenerationService._do_generate)
check('newline=""' in source, "V2 生成写临时文件那一行必须显式传 newline=\"\"")
check('tmp_path.write_text(v2_text, encoding="utf-8")' not in source, "不应该再是没有 newline 参数的旧写法")

print(f"\nALL {assertions} ASSERTIONS PASSED")
print("\n【诚实边界说明】以上验证证明了 newline=\"\" 这个参数本身的平台无关语义，")
print("以及 V2 生成逻辑确实已经改用它；但本沙箱是 Linux，天然无法复现")
print("\"Windows 上 os.linesep='\\r\\n' 导致 \\r\\r\\n 损坏\"这个具体故障——")
print("这一点必须由 bh 在真实 Windows 部署环境上，用真实数据重新生成 V2、")
print("在浏览器里查看 Clause Diff 来最终确认。")
