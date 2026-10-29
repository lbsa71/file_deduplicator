"""Streaming content checks with explicit stability checks."""

import hashlib
from itertools import zip_longest

from .ports import ChangedError

BLOCK = 1024 * 1024


def stable(fs, path, expected):
    if fs.stat(path) != expected:
        raise ChangedError(f'file changed during processing: {path}')


def fingerprint(fs, path, expected=None):
    before = fs.stat(path)
    if expected is not None:
        stable(fs, path, expected)
    full = hashlib.sha256()
    with fs.open_binary(path) as stream:
        prefix = stream.read(1024)
        full.update(prefix)
        while block := stream.read(BLOCK):
            full.update(block)
    stable(fs, path, before)
    return full.hexdigest(), hashlib.sha256(prefix).hexdigest()


def same_bytes(fs, left, right):
    before_left, before_right = fs.stat(left), fs.stat(right)
    with fs.open_binary(left) as a, fs.open_binary(right) as b:
        result = all(x == y for x, y in zip_longest(
            iter(lambda: a.read(BLOCK), b''), iter(lambda: b.read(BLOCK), b'')))
    stable(fs, left, before_left)
    stable(fs, right, before_right)
    return result
