from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .dialect import dialect_from_config, is_null, read_csv
from .headers import map_headers
from .keys import normalize_key
from .numbers import NumberParseError, format_numeric, parse_numeric


KEY_COLUMN = "order_id"


@dataclass(frozen=True)
class Candidate:
    value: str | Decimal
    display: str
    raw: str


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise ValueError("aliases config must be an object")
    if not isinstance(config.get("sources"), dict) or not isinstance(config.get("columns"), dict):
        raise ValueError("aliases config must contain sources and columns objects")
    return config


def merge_csv(sources_dir: str | Path, aliases_path: str | Path) -> dict:
    config = load_config(aliases_path)
    sources_config = config["sources"]
    columns = config["columns"]
    source_names = sorted(sources_config)

    if KEY_COLUMN not in columns:
        raise ValueError("configuration must define order_id")
    for unified, spec in columns.items():
        if spec.get("type") not in {"text", "money", "rate"}:
            raise ValueError(f"unsupported type for {unified}")
        if spec.get("primary") not in sources_config:
            raise ValueError(f"primary source for {unified} is unknown")

    records: dict[str, dict[str, dict[str, Candidate]]] = {source: {} for source in source_names}
    key_sources: dict[str, set[str]] = {}
    type_errors: list[dict] = []
    alias_conflicts: list[dict] = []
    matched_sources: dict[str, set[str]] = {}

    for source_name in source_names:
        dialect = dialect_from_config(sources_config[source_name])
        source_path = Path(sources_dir) / f"{source_name}.csv"
        parsed = read_csv(source_path, dialect)
        if not parsed:
            continue

        headers = parsed[0]
        header_mapping = map_headers(headers, columns)
        for unified, header in header_mapping.conflicts:
            alias_conflicts.append(
                {"source": source_name, "column": unified, "header": header}
            )
        for unified in header_mapping.indices:
            matched_sources.setdefault(unified, set()).add(source_name)

        key_index = header_mapping.indices.get(KEY_COLUMN)
        if key_index is None:
            raise ValueError(f"{source_name} does not contain order_id")

        for parsed_row in parsed[1:]:
            if key_index >= len(parsed_row):
                raise ValueError(f"{source_name} contains a row without order_id")
            key = normalize_key(parsed_row[key_index])
            if key in records[source_name]:
                raise ValueError(f"{source_name} contains duplicate order_id {key}")

            key_sources.setdefault(key, set()).add(source_name)
            row_values: dict[str, Candidate] = {}

            for unified, spec in columns.items():
                if unified == KEY_COLUMN:
                    continue
                column_index = header_mapping.indices.get(unified)
                if column_index is None or column_index >= len(parsed_row):
                    continue

                raw = parsed_row[column_index]
                if is_null(raw, dialect):
                    continue

                column_type = spec["type"]
                if column_type == "text":
                    display = raw.strip()
                    row_values[unified] = Candidate(display, display, raw)
                else:
                    try:
                        numeric_value = parse_numeric(raw, column_type)
                    except NumberParseError:
                        type_errors.append(
                            {
                                "source": source_name,
                                "order_id": key,
                                "column": unified,
                                "raw": raw,
                            }
                        )
                        continue
                    row_values[unified] = Candidate(
                        numeric_value,
                        format_numeric(numeric_value, column_type),
                        raw,
                    )

            records[source_name][key] = row_values

    rows = _build_rows(columns, source_names, records, key_sources)
    conflicts = _build_conflicts(columns, source_names, records, key_sources)

    aliases_used = [
        {
            "unified": unified,
            "primary": columns[unified]["primary"],
            "matched_sources": sorted(matched_sources.get(unified, set())),
        }
        for unified in sorted(columns)
    ]

    return {
        "rows": rows,
        "conflicts": conflicts,
        "type_errors": type_errors,
        "alias_conflicts": alias_conflicts,
        "summary": {
            "rows": len(rows),
            "conflicts": len(conflicts),
            "type_errors": len(type_errors),
            "alias_conflicts": len(alias_conflicts),
            "sources": len(source_names),
        },
        "aliases_used": aliases_used,
    }


def _build_rows(
    columns: dict,
    source_names: list[str],
    records: dict[str, dict[str, dict[str, Candidate]]],
    key_sources: dict[str, set[str]],
) -> list[dict]:
    rows = []
    for key in sorted(key_sources):
        row = {"order_id": key}
        for unified in [name for name in columns if name != KEY_COLUMN]:
            candidate = _select_candidate(columns, source_names, records, key, unified)
            row[unified] = None if candidate is None else candidate[1].display
        row["sources"] = sorted(key_sources[key])
        rows.append(row)
    return rows


def _build_conflicts(
    columns: dict,
    source_names: list[str],
    records: dict[str, dict[str, dict[str, Candidate]]],
    key_sources: dict[str, set[str]],
) -> list[dict]:
    conflicts = []
    for key in sorted(key_sources):
        for unified in [name for name in columns if name != KEY_COLUMN]:
            candidates = [
                (source_name, records[source_name][key][unified])
                for source_name in source_names
                if key in records[source_name] and unified in records[source_name][key]
            ]
            selected = _select_candidate(columns, source_names, records, key, unified)
            if selected is None:
                continue
            for source_name, candidate in candidates:
                if source_name == selected[0] or candidate.value == selected[1].value:
                    continue
                conflicts.append(
                    {
                        "order_id": key,
                        "column": unified,
                        "kept_value": selected[1].display,
                        "kept_source": selected[0],
                        "dropped_value": candidate.display,
                        "dropped_source": source_name,
                    }
                )
    return conflicts


def _select_candidate(
    columns: dict,
    source_names: list[str],
    records: dict[str, dict[str, dict[str, Candidate]]],
    key: str,
    unified: str,
) -> tuple[str, Candidate] | None:
    primary = columns[unified]["primary"]
    primary_candidate = records.get(primary, {}).get(key, {}).get(unified)
    if primary_candidate is not None:
        return primary, primary_candidate

    for source_name in source_names:
        candidate = records.get(source_name, {}).get(key, {}).get(unified)
        if candidate is not None:
            return source_name, candidate
    return None
