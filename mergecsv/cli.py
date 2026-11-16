from __future__ import annotations

import argparse

from .merge import merge_csv
from .report import summary_line, write_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge dialect-specific CSV order files.")
    parser.add_argument("--dir", required=True, dest="sources_dir")
    parser.add_argument("--aliases", required=True, dest="aliases_path")
    parser.add_argument("--out", required=True, dest="output_path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = merge_csv(args.sources_dir, args.aliases_path)
    write_report(report, args.output_path)
    print(summary_line(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
