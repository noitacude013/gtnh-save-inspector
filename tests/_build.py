"""Tiny NBT writer used by the test suite (the library itself is read-only)."""

from __future__ import annotations

import gzip
import struct


def _string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _payload(tag: int, value) -> bytes:
    if tag == 1:
        return struct.pack(">b", value)
    if tag == 2:
        return struct.pack(">h", value)
    if tag == 3:
        return struct.pack(">i", value)
    if tag == 4:
        return struct.pack(">q", value)
    if tag == 5:
        return struct.pack(">f", value)
    if tag == 6:
        return struct.pack(">d", value)
    if tag == 7:
        return struct.pack(">i", len(value)) + bytes(value)
    if tag == 8:
        return _string(value)
    if tag == 9:
        element_type, items = value
        out = bytes([element_type]) + struct.pack(">i", len(items))
        for item in items:
            out += _payload(element_type, item)
        return out
    if tag == 10:
        out = b""
        for name, item in value.items():
            item_tag, item_value = infer(item)
            out += bytes([item_tag]) + _string(name) + _payload(item_tag, item_value)
        return out + b"\x00"
    raise TypeError("cannot encode tag %r" % tag)


class Raw:
    """Explicit tag wrapper for values the writer cannot infer (long, short, ...)."""

    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


def infer(value):
    if isinstance(value, Raw):
        return value.tag, value.value
    if isinstance(value, tuple) and len(value) == 2:
        return 9, value  # explicit list: (element_tag, items)
    if isinstance(value, bool):
        return 1, int(value)
    if isinstance(value, int):
        return 3, value
    if isinstance(value, float):
        return 6, value
    if isinstance(value, str):
        return 8, value
    if isinstance(value, dict):
        return 10, value
    raise TypeError("test writer needs explicit (type, items) for lists: %r" % (value,))


def nbt_root(value, name: str = ""):
    return bytes([10]) + _string(name) + _payload(10, value)


def gzipped(value):
    return gzip.compress(nbt_root(value))
