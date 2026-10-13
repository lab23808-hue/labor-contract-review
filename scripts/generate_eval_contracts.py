"""生成 50 份评估合同样本 + 标准答案（CLI 入口）。

真正的生成逻辑在 `evaluation/generate_contracts.py::write_all()`，本脚本只是
一个薄的命令行包装，职责仅是：解析参数、调用、打印结果路径——不包含任何
生成逻辑本身，避免逻辑分散到两个地方。

用法：
    python scripts/generate_eval_contracts.py
    python scripts/generate_eval_contracts.py --output-dir /自定义路径

重新运行会覆盖 data/eval_samples/ 下的同名文件（生成器本身是纯函数式的——
同一份 evaluation/clause_bank.py + generate_contracts.py 代码，每次重新运行
产出完全相同的 50 份合同，不依赖随机数，可重复）。
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.generate_contracts import DATA_DIR, write_all  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATA_DIR,
        help=f"输出目录（默认 {DATA_DIR}）",
    )
    args = parser.parse_args()

    manifest = write_all(output_dir=args.output_dir)
    counts: dict = {}
    for s in manifest["samples"]:
        counts[s["sample_type"]] = counts.get(s["sample_type"], 0) + 1

    print(f"已生成 {len(manifest['samples'])} 份合同到 {args.output_dir}")
    print(f"实际分布：{counts}")
    print(f"  - {args.output_dir / 'contracts'}/*.txt  合同原文")
    print(f"  - {args.output_dir / 'answers'}/*.json    标准答案")
    print(f"  - {args.output_dir / 'manifest.json'}")
    print(f"  - {args.output_dir / 'rule_expectations.json'}")


if __name__ == "__main__":
    main()
