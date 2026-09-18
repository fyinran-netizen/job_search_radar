"""The acquisition byte pipeline: decompress, detect charset, decode."""

from __future__ import annotations

from dataclasses import dataclass
import codecs
import gzip
import re
import zlib


class DecodeError(ValueError):
    pass


@dataclass(frozen=True)
class DecodedContent:
    text: str
    charset: str
    content_encoding: str = ""


def decode_response(raw: bytes, headers: dict[str, str] | None = None) -> DecodedContent:
    headers = {key.lower(): value for key, value in (headers or {}).items()}
    encoding = headers.get("content-encoding", "").lower().strip()
    try:
        payload = _decompress(raw, encoding)
    except (OSError, zlib.error, ValueError) as exc:
        raise DecodeError(f"content decompression failed: {exc}") from exc
    charset = detect_charset(headers.get("content-type", ""), payload)
    try:
        text = payload.decode(charset, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise DecodeError(f"content decoding failed with charset {charset}: {exc}") from exc
    return DecodedContent(text=text, charset=charset, content_encoding=encoding)


def _decompress(raw: bytes, encoding: str) -> bytes:
    if not encoding or encoding == "identity":
        return raw
    encodings = [item.strip() for item in encoding.split(",") if item.strip()]
    payload = raw
    for item in reversed(encodings):
        if item == "gzip":
            payload = gzip.decompress(payload)
        elif item == "deflate":
            try:
                payload = zlib.decompress(payload)
            except zlib.error:
                payload = zlib.decompress(payload, -zlib.MAX_WBITS)
        else:
            raise DecodeError(f"unsupported content encoding: {item}")
    return payload


def detect_charset(content_type: str, raw: bytes) -> str:
    match = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", content_type, re.I)
    if not match:
        head = raw[:8192].decode("ascii", errors="ignore")
        match = re.search(r"<meta[^>]+charset\s*=\s*[\"']?([\w.-]+)", head, re.I)
    if match:
        candidate = match.group(1)
        try:
            return codecs.lookup(candidate).name
        except LookupError:
            raise DecodeError(f"unknown charset: {candidate}")
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        return "gb18030"
