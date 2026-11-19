"""
LaptopShare Framing Protocol
Defines binary packet headers, message types, serialization and deserialization.
"""

import json
import struct
from enum import IntEnum
from typing import Tuple, Dict, Any, Optional

MAGIC = b"LSH1"
MAGIC_LEN = 4
HEADER_FORMAT = ">4sBI"  # Magic (4B), MsgType (1B), PayloadLength (4B) = 9 bytes total
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

CHUNK_HEADER_FORMAT = ">IQI"  # FileID (4B), ChunkOffset (8B), ChunkLength (4B) = 16 bytes
CHUNK_HEADER_SIZE = struct.calcsize(CHUNK_HEADER_FORMAT)

DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024  # 2 MB high-throughput chunks for videos, photos & Wi-Fi 6

class MsgType(IntEnum):
    HANDSHAKE_REQ = 0x01
    HANDSHAKE_RESP = 0x02
    MANIFEST_REQ = 0x03
    MANIFEST_RESP = 0x04
    FILE_START = 0x05
    FILE_CHUNK = 0x06
    FILE_END = 0x07
    FILE_ACK = 0x08
    TRANSFER_COMPLETE = 0x09
    CANCEL = 0x0A
    PING = 0x0B
    PONG = 0x0C
    # Remote Browse & Pull Protocol Extensions
    BROWSE_AUTH_REQ = 0x10
    BROWSE_AUTH_RESP = 0x11
    BROWSE_LIST_REQ = 0x12
    BROWSE_LIST_RESP = 0x13
    PULL_REQ = 0x14
    PULL_RESP = 0x15
    # PC Migration Wizard Extensions
    MIGRATE_SCAN_REQ = 0x20
    MIGRATE_SCAN_RESP = 0x21
    MIGRATE_START_REQ = 0x22
    MIGRATE_START_RESP = 0x23

def encode_json_message(msg_type: MsgType, data: Dict[str, Any]) -> bytes:
    """Encodes a JSON payload into framed bytes."""
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = struct.pack(HEADER_FORMAT, MAGIC, int(msg_type), len(payload))
    return header + payload

def encode_file_chunk(file_id: int, offset: int, chunk_bytes: bytes) -> bytes:
    """Encodes a raw file chunk into a framed message."""
    chunk_len = len(chunk_bytes)
    chunk_meta = struct.pack(CHUNK_HEADER_FORMAT, file_id, offset, chunk_len)
    total_payload = chunk_meta + chunk_bytes
    header = struct.pack(HEADER_FORMAT, MAGIC, int(MsgType.FILE_CHUNK), len(total_payload))
    return header + total_payload

def decode_file_chunk_payload(payload: bytes) -> Tuple[int, int, bytes]:
    """Decodes a FILE_CHUNK payload into (file_id, offset, chunk_bytes)."""
    if len(payload) < CHUNK_HEADER_SIZE:
        raise ValueError("Payload too small for chunk header")
    file_id, offset, chunk_len = struct.unpack(CHUNK_HEADER_FORMAT, payload[:CHUNK_HEADER_SIZE])
    chunk_bytes = payload[CHUNK_HEADER_SIZE:CHUNK_HEADER_SIZE + chunk_len]
    return file_id, offset, chunk_bytes

def parse_header(header_bytes: bytes) -> Tuple[bytes, int, int]:
    """Parses a 9-byte header. Returns (magic, msg_type, payload_length)."""
    if len(header_bytes) != HEADER_SIZE:
        raise ValueError(f"Header must be {HEADER_SIZE} bytes")
    magic, msg_type, length = struct.unpack(HEADER_FORMAT, header_bytes)
    if magic != MAGIC:
        raise ValueError(f"Invalid magic: {magic}")
    return magic, msg_type, length

def read_exact(sock, num_bytes: int) -> bytes:
    """Reads exactly num_bytes from a socket or raises EOFError/ConnectionResetError."""
    buf = bytearray()
    while len(buf) < num_bytes:
        chunk = sock.recv(num_bytes - len(buf))
        if not chunk:
            raise EOFError("Socket closed prematurely")
        buf.extend(chunk)
    return bytes(buf)

def read_message(sock) -> Tuple[int, bytes]:
    """Reads the next framed message from the socket. Returns (msg_type, payload)."""
    header_data = read_exact(sock, HEADER_SIZE)
    _, msg_type, length = parse_header(header_data)
    payload = read_exact(sock, length) if length > 0 else b""
    return msg_type, payload
