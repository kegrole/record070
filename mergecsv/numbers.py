from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class NumberParseError(ValueError):
    pass


CURRENCY_PATTERN = re.compile(r"USD|EUR|GBP|CNY|RMB|[$€£¥￥]", re.IGNORECASE)
_MONEY_QUANTUM = Decimal("0.01")
_RATE_QUANTUM = Decimal("0.000001")


def parse_numeric(raw: str, column_type: str) -> Decimal:
    text = raw.strip()
    if not text:
        raise NumberParseError("empty numeric value")

    is_percentage = column_type == "rate" and text.endswith("%")
    if is_percentage:
        text = text[:-1].strip()

    text = CURRENCY_PATTERN.sub("", text).strip()
    negative = False

    if len(text) >= 2 and text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    elif text.endswith("-"):
        negative = True
        text = text[:-1].strip()

    if re.fullmatch(r"[0-9.,]+", text) is None:
        raise NumberParseError(raw)

    cleaned = _clean_separators(text, raw)
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise NumberParseError(raw) from exc

    if negative:
        value = -value
    if is_percentage:
        value /= Decimal(100)

    return round_numeric(value, column_type)


def _clean_separators(text: str, raw: str) -> str:
    comma_position = text.rfind(",")
    dot_position = text.rfind(".")

    if comma_position >= 0 and dot_position >= 0:
        if comma_position > dot_position:
            cleaned = text.replace(".", "").replace(",", ".")
        else:
            cleaned = text.replace(",", "")
    elif comma_position >= 0:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            cleaned = text.replace(",", "")
        elif len(parts) == 2:
            cleaned = text.replace(",", ".")
        else:
            raise NumberParseError(raw)
    elif dot_position >= 0:
        parts = text.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            cleaned = text.replace(".", "")
        elif len(parts) == 2:
            cleaned = text
        else:
            raise NumberParseError(raw)
    else:
        cleaned = text

    if re.fullmatch(r"\d+(?:\.\d+)?", cleaned) is None:
        raise NumberParseError(raw)
    return cleaned


def round_numeric(value: Decimal, column_type: str) -> Decimal:
    if column_type == "money":
        quantum = _MONEY_QUANTUM
    elif column_type == "rate":
        quantum = _RATE_QUANTUM
    else:
        raise ValueError(f"unsupported numeric column type: {column_type}")

    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    if rounded == 0:
        return Decimal(0).quantize(quantum)
    return rounded


def format_numeric(value: Decimal, column_type: str) -> str:
    rounded = round_numeric(value, column_type)
    if column_type == "money":
        return f"{rounded:f}"

    rendered = f"{rounded:f}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered
