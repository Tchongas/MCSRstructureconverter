"""
Serialize a parsed `nbt.Tag` tree back into SNBT (the string form used in
Minecraft commands, e.g. `{Items:[{Slot:0b,...}]}`).
"""

from __future__ import annotations

import re

from nbt import (
    Tag,
    TAG_BYTE,
    TAG_SHORT,
    TAG_INT,
    TAG_LONG,
    TAG_FLOAT,
    TAG_DOUBLE,
    TAG_BYTE_ARRAY,
    TAG_STRING,
    TAG_LIST,
    TAG_COMPOUND,
    TAG_INT_ARRAY,
    TAG_LONG_ARRAY,
)

_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")


def _quote_string(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _key(name: str) -> str:
    return name if _BARE_KEY_RE.match(name) else _quote_string(name)


def _num(value, suffix: str) -> str:
    if suffix in ("f", "d") and float(value).is_integer():
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def to_snbt(tag: Tag) -> str:
    tid, value = tag.id, tag.value

    if tid == TAG_BYTE:
        return _num(value, "b")
    if tid == TAG_SHORT:
        return _num(value, "s")
    if tid == TAG_INT:
        return str(value)
    if tid == TAG_LONG:
        return _num(value, "l")
    if tid == TAG_FLOAT:
        return _num(value, "f")
    if tid == TAG_DOUBLE:
        return _num(value, "d")
    if tid == TAG_STRING:
        return _quote_string(value)
    if tid == TAG_BYTE_ARRAY:
        return "[B;" + ",".join(f"{b}b" for b in value) + "]"
    if tid == TAG_INT_ARRAY:
        return "[I;" + ",".join(str(i) for i in value) + "]"
    if tid == TAG_LONG_ARRAY:
        return "[L;" + ",".join(f"{v}l" for v in value) + "]"
    if tid == TAG_LIST:
        _, items = value
        return "[" + ",".join(to_snbt(t) for t in items) + "]"
    if tid == TAG_COMPOUND:
        parts = [f"{_key(k)}:{to_snbt(v)}" for k, v in value.items()]
        return "{" + ",".join(parts) + "}"

    raise ValueError(f"Cannot serialize tag id {tid} to SNBT")


def compound_to_snbt(tag: Tag, exclude: "set[str] | None" = None) -> str:
    """SNBT for a TAG_COMPOUND, optionally dropping some top-level keys
    (e.g. 'Id'/'Pos' from a BlockEntity, which aren't valid in a
    `data merge block` payload)."""
    if tag.id != TAG_COMPOUND:
        raise TypeError("compound_to_snbt() requires a TAG_COMPOUND")
    exclude = exclude or set()
    parts = [f"{_key(k)}:{to_snbt(v)}" for k, v in tag.value.items() if k not in exclude]
    return "{" + ",".join(parts) + "}"
