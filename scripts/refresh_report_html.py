from __future__ import annotations

import argparse
import json
from pathlib import Path

from generate_analysis_report import render


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "data" / "analysis_reports"


def refresh(directory: Path) -> Path:
    json_files = sorted(directory.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"目录中没有报告 JSON：{directory}")
    payload_path = json_files[-1]
    html_files = sorted(directory.glob("*.html"))
    html_path = html_files[-1] if html_files else payload_path.with_suffix(".html")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    html_path.write_text(render(payload), encoding="utf-8")
    return html_path


def main() -> int:
    parser = argparse.ArgumentParser(description="按最新模板重建既有赛前分析 HTML，不改分析数据")
    parser.add_argument("directories", nargs="+", help="analysis_reports 下的时间戳目录名或完整路径")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    args = parser.parse_args()

    root = Path(args.root)
    outputs = []
    for value in args.directories:
        directory = Path(value)
        if not directory.is_absolute():
            directory = root / directory
        outputs.append(str(refresh(directory)))
    print(json.dumps({"refreshed": outputs, "analysis_data_changed": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
