"""Strict reader for the QCA-ATH6KL firmware container (init.c IE format)."""
import hashlib
import struct
from pathlib import Path

MAGIC = b'QCA-ATH6KL\0'
EXPECTED = {
    'fw.ram.bin': 'c2ea9b6fcadccd268fd8838f68a9cff80a6020f1dd60095a3a59bd8f437445f1',
    'bdata.bin': '590b23c1a477cc7b4ab8b3f5f4fec26820fe80ef6a283aa3a3e553b13523c73d',
}

def parse_container(data):
    if not data.startswith(MAGIC):
        raise ValueError('Invalid QCA firmware magic')
    offset = len(MAGIC)
    entries = {}
    while offset < len(data):
        if len(data) - offset < 8:
            raise ValueError('Truncated IE header')
        kind, size = struct.unpack_from('<II', data, offset)
        offset += 8
        if size > len(data) - offset:
            raise ValueError('Truncated IE payload')
        if kind in entries:
            raise ValueError('Duplicate firmware IE')
        entries[kind] = data[offset:offset + size]
        offset += size
    if not entries.get(3):
        raise ValueError('Missing firmware image')
    for kind in (5, 7, 8, 9):
        if kind in entries and len(entries[kind]) != 4:
            raise ValueError('Invalid scalar IE length')
    return entries

def load_verified(directory):
    blobs = {}
    for name, digest in EXPECTED.items():
        data = (Path(directory) / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Unverified firmware asset: ' + name)
        blobs[name] = data
    if len(blobs['bdata.bin']) != 6144:
        raise ValueError('Incorrect board data size')
    return parse_container(blobs['fw.ram.bin']), blobs['bdata.bin']
