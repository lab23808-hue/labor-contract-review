"""生成 50 份评估合同与标准答案。"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.generate_contracts import DATA_DIR, write_all  # noqa: E402


def main() -> None:
    manifest = write_all()
    print(f"已生成 {len(manifest['samples'])} 份评估合同到 {DATA_DIR}")
    print("分布：", manifest["distribution"])


if __name__ == "__main__":
    main()
