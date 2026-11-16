from __future__ import annotations

from dataclasses import dataclass


HEADER_WHITESPACE = " \t\n\r\u00a0\u3000"


def normalize_header(value: str) -> str:
    value = value.removeprefix("\ufeff")
    value = value.strip(HEADER_WHITESPACE)
    value = value.replace("_", " ").replace("-", " ")

    words: list[str] = []
    current: list[str] = []
    for char in value:
        if char in HEADER_WHITESPACE:
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        words.append("".join(current))
    return " ".join(words).lower()


@dataclass(frozen=True)
class HeaderMapping:
    indices: dict[str, int]
    conflicts: list[tuple[str, str]]


def map_headers(headers: list[str], columns: dict) -> HeaderMapping:
    aliases: dict[str, str] = {}
    for unified, spec in columns.items():
        for alias in spec["aliases"]:
            normalized_alias = normalize_header(alias)
            if normalized_alias in aliases and aliases[normalized_alias] != unified:
                raise ValueError(f"alias {alias!r} is assigned to multiple columns")
            aliases[normalized_alias] = unified

    matches: dict[str, list[tuple[int, str]]] = {}
    for index, header in enumerate(headers):
        unified = aliases.get(normalize_header(header))
        if unified is not None:
            matches.setdefault(unified, []).append((index, header))

    indices: dict[str, int] = {}
    conflicts: list[tuple[str, str]] = []
    for unified, matched in matches.items():
        if len(matched) == 1:
            indices[unified] = matched[0][0]
        else:
            for _, header in matched[1:]:
                conflicts.append((unified, header))

    return HeaderMapping(indices, conflicts)
