#!/usr/bin/env python3
"""Build the static GitHub Pages artifact from generated project pages."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "site"
PUBLIC_DATA_DIRS = (
    "analysis_reports",
    "match_workspace",
    "postmatch_dashboard",
)


def copy_tree(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copytree(source, target, dirs_exist_ok=True)


def build(output: Path) -> Path:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    data_root = ROOT / "data"
    for name in PUBLIC_DATA_DIRS:
        copy_tree(data_root / name, output / name)

    downloads = output / "downloads"
    downloads.mkdir(exist_ok=True)
    workbooks = sorted(
        (ROOT / "outputs").glob("**/*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if workbooks:
        shutil.copy2(workbooks[0], downloads / workbooks[0].name)

    (output / ".nojekyll").write_text("", encoding="utf-8")
    (output / "index.html").write_text(
        """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="0;url=match_workspace/latest.html">
  <title>Football Betting OneShot</title>
</head>
<body>
  <p><a href="match_workspace/latest.html">进入 Football Betting OneShot 比赛工作台</a></p>
</body>
</html>
""",
        encoding="utf-8",
    )
    return output / "index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    print(build(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
