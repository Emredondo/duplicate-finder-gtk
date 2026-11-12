# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded reads and no-follow opens, including all parent directories."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import stat
import threading

BLOCK_SIZE = 1024 * 1024
SAMPLE_SIZE = 64 * 1024


class Cancelled(Exception):
    pass


class FileChanged(OSError):
    pass


class Cancellation:
    def __init__(self):
        self.event = threading.Event()

    def cancel(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise Cancelled()


@contextmanager
def directory_fd(path):
    """Open an absolute directory without following any symlink component."""
    path = Path(os.path.abspath(path))
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                            os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def current_stat(record):
    with directory_fd(record.path.parent) as fd:
        st = os.stat(record.path.name, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode) or not record.matches(st):
        raise FileChanged(f"Archivo modificado o sustituido: {record.path}")
    return st


@contextmanager
def checked_open(record):
    with directory_fd(record.path.parent) as directory:
        fd = os.open(record.path.name, os.O_RDONLY | os.O_NOFOLLOW |
                     os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not record.matches(st):
            raise FileChanged(f"Archivo modificado o sustituido: {record.path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            yield stream
            if not record.matches(os.fstat(fd)):
                raise FileChanged(f"El archivo cambió durante la lectura: {record.path}")
            current_stat(record)
    finally:
        os.close(fd)


def partial_hash(record, cancel):
    digest = hashlib.sha256()
    with checked_open(record) as stream:
        offsets = sorted({0, max(0, (record.size - SAMPLE_SIZE) // 2),
                          max(0, record.size - SAMPLE_SIZE)})
        for offset in offsets:
            cancel.check()
            stream.seek(offset)
            digest.update(stream.read(SAMPLE_SIZE))
    return digest.hexdigest()


def full_hash(record, cancel):
    digest = hashlib.sha256()
    with checked_open(record) as stream:
        while True:
            cancel.check()
            block = stream.read(BLOCK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def identical(first, second, cancel):
    """Compare bytes even when SHA-256 agrees; check snapshots before and after."""
    if first.size != second.size:
        return False
    equal = True
    with checked_open(first) as a, checked_open(second) as b:
        while True:
            cancel.check()
            left, right = a.read(BLOCK_SIZE), b.read(BLOCK_SIZE)
            if left != right:
                equal = False
                break
            if not left:
                break
    return equal
