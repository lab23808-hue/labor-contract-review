"""对 build_snapshot_fingerprint.py 的自测（任务 C 要求的 6 种情况）。

用法：在项目根目录下运行
    python scripts/test_snapshot_fingerprint.py

本脚本只在系统临时目录（tempfile.mkdtemp()）里对项目文件的**副本**做增/删/改操作，
从不写入真实的 data/knowledge、data/chroma、data/eval_samples，运行结束后临时副本
会被清理掉。
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_snapshot_fingerprint as bsf

WORK = Path(tempfile.mkdtemp(prefix="rag_snapshot_fp_test_"))


def fresh_copy(name: str) -> Path:
    dst = WORK / name
    if dst.exists():
        shutil.rmtree(dst)
    # 只拷贝本工具真正需要的子树，避免复制 .venv/data/chroma 等大体积目录
    dst.mkdir(parents=True)
    for sub in ("rag", "config", "schemas.py"):
        src = PROJECT_ROOT / sub
        if src.is_dir():
            shutil.copytree(src, dst / sub)
        elif src.is_file():
            shutil.copy2(src, dst / sub)
    shutil.copytree(PROJECT_ROOT / "data" / "knowledge", dst / "data" / "knowledge", dirs_exist_ok=True)
    (dst / "data" / "eval_samples").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        PROJECT_ROOT / "data" / "eval_samples" / "retrieval_eval_samples.json",
        dst / "data" / "eval_samples" / "retrieval_eval_samples.json",
    )
    return dst


results = {}

try:
    # ---- 测试 1：相同输入重复生成，指纹一致 ----
    root1a = fresh_copy("case1_a")
    snap1a = bsf.build_full_snapshot(root1a, note="case1_a")
    root1b = fresh_copy("case1_b")
    snap1b = bsf.build_full_snapshot(root1b, note="case1_b")
    results["test1_identical_input_same_fingerprint"] = (
        snap1a["overall_content_fingerprint"] == snap1b["overall_content_fingerprint"]
    )

    # ---- 测试 2：修改一条 Evidence 文本 ----
    # 用二进制模式追加字节，不经过文本模式的换行符转换——Windows 上 open(..., "w")/
    # Path.write_text() 默认会把 "\n" 回写成 "\r\n"（os.linesep），如果原文件混用过
    # 换行符风格，这个"正常化"会连带改动很多条文内部的换行符，导致看起来像是改了
    # 很多条 Evidence，其实只是写入方式本身引入的副作用，不是本来想测的"改一个字符"。
    # 二进制模式只在文件末尾追加原样字节，不触碰已有内容的任何一个字节。
    root2 = fresh_copy("case2")
    snap2_before = bsf.build_full_snapshot(root2, note="case2_before")
    kfiles = list((root2 / "data" / "knowledge").glob("*.txt"))
    kfile = kfiles[0]
    with open(kfile, "ab") as f:
        f.write("\n（测试追加字符）".encode("utf-8"))
    snap2_after = bsf.build_full_snapshot(root2, note="case2_after")
    diff2 = bsf.diff_snapshots(snap2_before, snap2_after)
    results["test2_evidence_text_change_detected"] = diff2["knowledge_changed"]
    results["test2_diff"] = diff2

    # ---- 测试 3：删除一份法律文件 ----
    root3 = fresh_copy("case3")
    snap3_before = bsf.build_full_snapshot(root3, note="case3_before")
    list((root3 / "data" / "knowledge").glob("*.txt"))[0].unlink()
    snap3_after = bsf.build_full_snapshot(root3, note="case3_after")
    diff3 = bsf.diff_snapshots(snap3_before, snap3_after)
    results["test3_file_deletion_detected"] = diff3["knowledge_changed"]

    # ---- 测试 4：修改评估标准答案 ----
    root4 = fresh_copy("case4")
    snap4_before = bsf.build_full_snapshot(root4, note="case4_before")
    eval_path = root4 / "data" / "eval_samples" / "retrieval_eval_samples.json"
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    for s in data["samples"]:
        if s["evaluable"] and s["relevant"]:
            s["relevant"][0]["article"] = "第九十九条（测试修改）"
            break
    eval_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    snap4_after = bsf.build_full_snapshot(root4, note="case4_after")
    results["test4_gold_answer_change_detected"] = (
        snap4_before["eval_dataset"]["gold_answer_content_fingerprint"]
        != snap4_after["eval_dataset"]["gold_answer_content_fingerprint"]
    )
    results["test4_knowledge_fingerprint_unaffected"] = (
        snap4_before["knowledge"]["knowledge_snapshot_fingerprint"]
        == snap4_after["knowledge"]["knowledge_snapshot_fingerprint"]
    )

    # ---- 测试 5：只改生成时间，不改内容 ----
    root5 = fresh_copy("case5")
    snap5_t1 = bsf.build_full_snapshot(root5, note="t1")
    time.sleep(1.2)
    snap5_t2 = bsf.build_full_snapshot(root5, note="t2")
    results["test5_generated_at_differs"] = snap5_t1["generated_at"] != snap5_t2["generated_at"]
    results["test5_overall_fingerprint_unchanged"] = (
        snap5_t1["overall_content_fingerprint"] == snap5_t2["overall_content_fingerprint"]
    )

    # ---- 测试 6：diff 定位具体变化 ----
    results["test6_evidence_diff_detail"] = diff2["evidence_diff"]
    results["test6_file_diff_detail"] = diff2["knowledge_file_diff"]

finally:
    shutil.rmtree(WORK, ignore_errors=True)

print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
all_pass = all(
    v for k, v in results.items() if k.startswith("test") and isinstance(v, bool)
)
print("\n全部布尔类测试是否通过：", all_pass)
