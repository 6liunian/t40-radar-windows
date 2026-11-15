"""AR6004 hw3.0 RAM boot sequence adapted from ath6kl init.c/bmi.c.

Copyright (c) 2004-2011 Atheros Communications Inc.
Copyright (c) 2011-2012 Qualcomm Atheros, Inc.
Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""
import struct
from .firmware import load_verified

def boot(transfer, directory):
    entries, board = load_verified(directory)
    if set(entries) != {0, 1, 3, 6}:
        raise ValueError('Firmware layout requires a different boot sequence')
    def send(*words, data=b''):
        transfer(False, 1, struct.pack('<' + 'I' * len(words), *words) + data)
    def read32(address, register=False):
        if register:
            send(6, address)
        else:
            send(2, address, 4)
        return struct.unpack('<I', transfer(True, 2, 4))[0]
    def write32(address, value, register=False):
        if register:
            send(7, address, value)
        else:
            send(3, address, 4, value)
    def hi(offset, value):
        write32(0x400800 + offset, value)
    hi(0x14, 0)
    hi(0, 2)
    hi(0x10, read32(0x400810) | (1 << 9) | (1 << 12))
    for offset, value in ((0xac, 0), (0x68, 7168), (0x6c, 16), (0x74, 99), (0x80, 11)):
        hi(offset, value)
    options = read32(0x180c0, True)
    sleep = read32(0x40c4, True)
    write32(0x180c0, options | 8, True)
    write32(0x40c4, sleep | 1, True)
    write32(0x40e0, 1 << 20, True)
    hi(0x54, 0x436400)
    for offset in range(0, len(board), 240):
        chunk = board[offset:offset + 240]
        send(3, 0x436400 + offset, len(chunk), data=chunk)
    hi(0x58, len(board))
    print('BOARD_LOADED', len(board), flush=True)
    image = entries[3]
    send(13, 0x1234)
    aligned = len(image) & ~3
    for offset in range(0, aligned, 244):
        chunk = image[offset:min(offset + 244, aligned)]
        send(14, len(chunk), data=chunk)
    if aligned != len(image):
        send(14, 4, data=image[aligned:].ljust(4, b'\0'))
    send(13, 0)
    print('FIRMWARE_LOADED', len(image), flush=True)
    write32(0x40c4, sleep, True)
    write32(0x180c0, options | 0x20, True)
    send(1)
    print('BMI_DONE', flush=True)
