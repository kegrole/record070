from __future__ import annotations


def normalize_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise ValueError("order_id must not be empty")
    return key
