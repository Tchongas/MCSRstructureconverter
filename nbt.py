"""
Minimal, dependency-free NBT reader.

Supports every tag type used by the NBT spec (as used by WorldEdit .schem
files): End, Byte, Short, Int, Long, Float, Double, Byte Array, String,
List, Compound, Int Array, Long Array.

Every tag is parsed into a `Tag` instance that keeps track of its original
tag id, so values can later be re-serialized to SNBT with the correct
numeric suffix (b/s/l/f/d).
"""

from __future__ import annotations

import gzip
import struct
import zlib
from typing import Any, Dict, List, Tuple

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12


class Tag:
    """A typed NBT value.

    - Compound: value is a dict[str, Tag]
    - List: value is a tuple (element_tag_id, list[Tag])
    - ByteArray/IntArray/LongArray: value is list[int]
    - Everything else: value is the plain python scalar (int/float/str)
    """

    __slots__ = ("id", "value")

    def __init__(self, tag_id: int, value: Any):
        self.id = tag_id
        self.value = value

    def __repr__(self):
        return f"Tag({self.id}, {self.value!r})"

    # Convenience helpers -------------------------------------------------
    def get(self, key: str, default: "Tag | None" = None) -> "Tag | None":
        if self.id != TAG_COMPOUND:
            raise TypeError("get() only valid on TAG_COMPOUND")
        return self.value.get(key, default)

    def unwrap(self) -> Any:
        """Recursively convert this Tag tree into plain python data
        (dict/list/scalars). Compound keys map to unwrapped values.
        Type information (b/s/l/f/d suffixes) is lost - use for structural
        fields only (Width, Height, Palette, ...), not for round-tripping
        arbitrary NBT."""
        if self.id == TAG_COMPOUND:
            return {k: v.unwrap() for k, v in self.value.items()}
        if self.id == TAG_LIST:
            _, items = self.value
            return [t.unwrap() for t in items]
        if self.id in (TAG_BYTE_ARRAY, TAG_INT_ARRAY, TAG_LONG_ARRAY):
            return list(self.value)
        return self.value


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        chunk = self.data[self.pos:self.pos + n]
        if len(chunk) != n:
            raise EOFError("Unexpected end of NBT data")
        self.pos += n
        return chunk

    def read_byte(self) -> int:
        return struct.unpack(">b", self.read(1))[0]

    def read_ubyte(self) -> int:
        return struct.unpack(">B", self.read(1))[0]

    def read_short(self) -> int:
        return struct.unpack(">h", self.read(2))[0]

    def read_int(self) -> int:
        return struct.unpack(">i", self.read(4))[0]

    def read_long(self) -> int:
        return struct.unpack(">q", self.read(8))[0]

    def read_float(self) -> float:
        return struct.unpack(">f", self.read(4))[0]

    def read_double(self) -> float:
        return struct.unpack(">d", self.read(8))[0]

    def read_string(self) -> str:
        length = struct.unpack(">H", self.read(2))[0]
        return self.read(length).decode("utf-8")

    def read_payload(self, tag_id: int) -> Any:
        if tag_id == TAG_BYTE:
            return self.read_byte()
        if tag_id == TAG_SHORT:
            return self.read_short()
        if tag_id == TAG_INT:
            return self.read_int()
        if tag_id == TAG_LONG:
            return self.read_long()
        if tag_id == TAG_FLOAT:
            return self.read_float()
        if tag_id == TAG_DOUBLE:
            return self.read_double()
        if tag_id == TAG_BYTE_ARRAY:
            length = self.read_int()
            return [self.read_byte() for _ in range(length)]
        if tag_id == TAG_STRING:
            return self.read_string()
        if tag_id == TAG_LIST:
            elem_id = self.read_ubyte()
            length = self.read_int()
            items = [Tag(elem_id, self.read_payload(elem_id)) for _ in range(length)]
            return (elem_id, items)
        if tag_id == TAG_COMPOUND:
            result: Dict[str, Tag] = {}
            while True:
                child_id = self.read_ubyte()
                if child_id == TAG_END:
                    break
                name = self.read_string()
                result[name] = Tag(child_id, self.read_payload(child_id))
            return result
        if tag_id == TAG_INT_ARRAY:
            length = self.read_int()
            return [self.read_int() for _ in range(length)]
        if tag_id == TAG_LONG_ARRAY:
            length = self.read_int()
            return [self.read_long() for _ in range(length)]
        raise ValueError(f"Unknown NBT tag id: {tag_id}")

    def read_named_tag(self) -> Tuple[str, Tag]:
        tag_id = self.read_ubyte()
        if tag_id == TAG_END:
            return "", Tag(TAG_END, None)
        name = self.read_string()
        value = self.read_payload(tag_id)
        return name, Tag(tag_id, value)


def _decompress(raw: bytes) -> bytes:
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw


def load(path: str) -> Tuple[str, Tag]:
    """Load a (possibly gzip/zlib compressed) NBT file. Returns (root_name, root_tag)."""
    with open(path, "rb") as f:
        raw = f.read()
    data = _decompress(raw)
    reader = _Reader(data)
    return reader.read_named_tag()
