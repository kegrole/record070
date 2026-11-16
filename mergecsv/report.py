from __future__ import annotations

import json
from pathlib import Path


def write_report(report: dict, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, sort_keys=False)
        output.write("\n")


def summary_line(report: dict) -> str:
    summary = report["summary"]
    return (
        f"合并行数: {summary['rows']}，冲突数: {summary['conflicts']}，"
        f"类型错误数: {summary['type_errors']}，别名冲突数: {summary['alias_conflicts']}，"
        f"来源数: {summary['sources']}"
    )
