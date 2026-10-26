"""Minimal, dependency-free NBT reader for Minecraft 1.7.10 (big-endian, Java edition).

Only reading is supported: this tool never writes into a world save.
"""

from __future__ import annotations

import gzip
import struct
import zlib

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

TAG_NAMES = {
    TAG_END: "end",
    TAG_BYTE: "byte",
    TAG_SHORT: "short",
    TAG_INT: "int",
    TAG_LONG: "long",
    TAG_FLOAT: "float",
    TAG_DOUBLE: "double",
    TAG_BYTE_ARRAY: "byte_array",
    TAG_STRING: "string",
    TAG_LIST: "list",
    TAG_COMPOUND: "compound",
    TAG_INT_ARRAY: "int_array",
    TAG_LONG_ARRAY: "long_array",
}


class NbtError(ValueError):
    """Raised when a payload cannot be parsed as NBT."""


class _Reader:
    __slots__ = ("buf", "pos", "end")

    def __init__(self, buf: bytes, pos: int = 0):
        self.buf = buf
        self.pos = pos
        self.end = len(buf)

    def _need(self, count: int) -> None:
        if self.pos + count > self.end:
            raise NbtError(
                "unexpected end of NBT payload at %d (need %d bytes)" % (self.pos, count)
            )

    def u8(self) -> int:
        self._need(1)
        value = self.buf[self.pos]
        self.pos += 1
        return value

    def i8(self) -> int:
        self._need(1)
        value = struct.unpack_from(">b", self.buf, self.pos)[0]
        self.pos += 1
        return value

    def i16(self) -> int:
        self._need(2)
        value = struct.unpack_from(">h", self.buf, self.pos)[0]
        self.pos += 2
        return value

    def i32(self) -> int:
        self._need(4)
        value = struct.unpack_from(">i", self.buf, self.pos)[0]
        self.pos += 4
        return value

    def i64(self) -> int:
        self._need(8)
        value = struct.unpack_from(">q", self.buf, self.pos)[0]
        self.pos += 8
        return value

    def f32(self) -> float:
        self._need(4)
        value = struct.unpack_from(">f", self.buf, self.pos)[0]
        self.pos += 4
        return value

    def f64(self) -> float:
        self._need(8)
        value = struct.unpack_from(">d", self.buf, self.pos)[0]
        self.pos += 8
        return value

    def raw(self, count: int) -> bytes:
        self._need(count)
        value = self.buf[self.pos : self.pos + count]
        self.pos += count
        return value

    def string(self) -> str:
        length = self.i16()
        if length < 0:
            raise NbtError("negative string length %d" % length)
        return self.raw(length).decode("utf-8", "replace")

    def advance(self, count: int) -> None:
        self._need(count)
        self.pos += count

    def payload(self, tag: int):
        if tag == TAG_BYTE:
            return self.i8()
        if tag == TAG_SHORT:
            return self.i16()
        if tag == TAG_INT:
            return self.i32()
        if tag == TAG_LONG:
            return self.i64()
        if tag == TAG_FLOAT:
            return self.f32()
        if tag == TAG_DOUBLE:
            return self.f64()
        if tag == TAG_BYTE_ARRAY:
            length = self.i32()
            if length < 0:
                raise NbtError("negative byte array length %d" % length)
            return self.raw(length)
        if tag == TAG_STRING:
            return self.string()
        if tag == TAG_LIST:
            element_type = self.u8()
            length = self.i32()
            if length < 0:
                raise NbtError("negative list length %d" % length)
            return [self.payload(element_type) for _ in range(length)]
        if tag == TAG_COMPOUND:
            result = {}
            while True:
                child_type = self.u8()
                if child_type == TAG_END:
                    return result
                name = self.string()
                result[name] = self.payload(child_type)
        if tag == TAG_INT_ARRAY:
            length = self.i32()
            if length < 0:
                raise NbtError("negative int array length %d" % length)
            return [self.i32() for _ in range(length)]
        if tag == TAG_LONG_ARRAY:
            length = self.i32()
            if length < 0:
                raise NbtError("negative long array length %d" % length)
            return [self.i64() for _ in range(length)]
        raise NbtError("unknown NBT tag type %d at offset %d" % (tag, self.pos))


def parse_nbt(data: bytes):
    """Parse a complete NBT root tag and return its payload (usually a dict)."""
    reader = _Reader(data)
    tag = reader.u8()
    if tag == TAG_END:
        raise NbtError("empty NBT root tag")
    reader.string()  # root name, conventionally empty
    return reader.payload(tag)


def decompress(payload: bytes, compression: int) -> bytes:
    """Decompress an Anvil chunk payload (compression byte from the region file)."""
    if compression == 1:
        return gzip.decompress(payload)
    if compression == 2:
        return zlib.decompress(payload)
    if compression == 3:
        return payload
    raise NbtError("unknown chunk compression type %d" % compression)


def load_bytes(data: bytes):
    """Parse NBT from memory, transparently decompressing gzip/zlib payloads."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    elif data[:1] == b"\x78":
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
    return parse_nbt(data)


def sanitize(value):
    """Convert parsed NBT into JSON-serialisable values (bytes become hex strings)."""
    if isinstance(value, (bytes, bytearray)):
        return {"hex": bytes(value).hex()}
    if isinstance(value, dict):
        return {str(key): sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def squash(value, max_items: int = 64):
    """Like sanitize() but truncates long arrays (byte/int/long arrays) for display."""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        return {
            "len": len(raw),
            "hex": raw[:max_items].hex(),
            "truncated": len(raw) > max_items,
        }
    if isinstance(value, dict):
        return {str(key): squash(item, max_items) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > max_items:
            return [squash(item, max_items) for item in value[:max_items]] + [
                "... (%d more)" % (len(value) - max_items)
            ]
        return [squash(item, max_items) for item in value]
    return value
