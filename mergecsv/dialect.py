from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceDialect:
    delimiter: str
    escape: str
    nulls: tuple[str, ...]
    encoding: str


def dialect_from_config(config: dict) -> SourceDialect:
    delimiter = config["delimiter"]
    escape = config["escape"]
    nulls = config["nulls"]
    encoding = config["encoding"]

    if not isinstance(delimiter, str) or len(delimiter) != 1:
        raise ValueError("delimiter must be one character")
    if escape not in {"doubling", "backslash"}:
        raise ValueError("escape must be 'doubling' or 'backslash'")
    if not isinstance(nulls, list) or not all(isinstance(item, str) for item in nulls):
        raise ValueError("nulls must be a list of strings")
    if not isinstance(encoding, str) or not encoding:
        raise ValueError("encoding must be a non-empty string")

    return SourceDialect(delimiter, escape, tuple(nulls), encoding)


def read_csv(path: str | Path, dialect: SourceDialect) -> list[list[str]]:
    with open(path, "r", encoding=dialect.encoding, newline="") as source:
        text = source.read()

    if text.startswith("\ufeff"):
        text = text[1:]
    return parse_csv(text, dialect)


def parse_csv(text: str, dialect: SourceDialect) -> list[list[str]]:
    if text == "":
        return []

    rows: list[list[str]] = []
    row: list[str] = []
    field: list[str] = []
    in_quotes = False
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if in_quotes:
            if dialect.escape == "backslash" and char == "\\" and index + 1 < length:
                field.append(text[index + 1])
                index += 2
                continue
            if (
                dialect.escape == "doubling"
                and char == '"'
                and index + 1 < length
                and text[index + 1] == '"'
            ):
                field.append('"')
                index += 2
                continue
            if char == '"':
                in_quotes = False
            else:
                field.append(char)
        elif char == '"':
            in_quotes = True
        elif char == dialect.delimiter:
            row.append("".join(field))
            field = []
        elif char == "\r" or char == "\n":
            if char == "\r" and index + 1 < length and text[index + 1] == "\n":
                index += 1
            row.append("".join(field))
            rows.append(row)
            row = []
            field = []
        else:
            field.append(char)

        index += 1

    if in_quotes:
        raise ValueError("unterminated quoted field")
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return rows


def is_null(value: str, dialect: SourceDialect) -> bool:
    return value.strip() in dialect.nulls
