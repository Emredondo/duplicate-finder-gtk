# SPDX-License-Identifier: GPL-3.0-or-later
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import fnmatch
import os
import stat
import time

from .hashing import (Cancellation, Cancelled, directory_fd, partial_hash,
                      full_hash, identical, current_stat)
from .model import DuplicateGroup, FileRecord, ScanResult


@dataclass(frozen=True)
class ScanOptions:
    recursive: bool = True
    hidden: bool = False
    exclusions: tuple[str, ...] = (".Trash", ".Trash-*")


@dataclass(frozen=True)
class Progress:
    stage: str
    done: int
    total: int
    examined: int
    path: str = ""


class Scanner:
    def __init__(self, options=None, cancel=None, on_progress=None):
        self.options = options or ScanOptions()
        self.cancel = cancel or Cancellation()
        self.on_progress = on_progress or (lambda progress: None)
        self._last_report = 0

    def report(self, stage, done, total, result, path="", force=False):
        now = time.monotonic()
        if force or now - self._last_report >= 0.1:
            self._last_report = now
            self.on_progress(Progress(stage, done, total, result.examined, str(path)))

    def excluded(self, name, relative):
        return ((not self.options.hidden and name.startswith(".")) or
                any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(relative, p)
                    for p in self.options.exclusions if p))

    def inventory(self, root, result):
        sizes, seen = defaultdict(list), set()
        pending = [root]
        while pending:
            self.cancel.check()
            folder = pending.pop()
            try:
                with directory_fd(folder) as fd, os.scandir(fd) as entries:
                    for entry in entries:
                        self.cancel.check()
                        path = folder / entry.name
                        if self.excluded(entry.name, str(path.relative_to(root))):
                            continue
                        try:
                            st = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(st.st_mode):
                                result.symlinks_skipped += 1
                            elif stat.S_ISDIR(st.st_mode):
                                if self.options.recursive:
                                    pending.append(path)
                            elif stat.S_ISREG(st.st_mode):
                                result.examined += 1
                                identity = (st.st_dev, st.st_ino)
                                if identity in seen:
                                    result.hardlinks_skipped += 1
                                else:
                                    seen.add(identity)
                                    sizes[st.st_size].append(FileRecord.from_stat(path, st))
                            self.report("Inventario", result.examined, 0, result, path)
                        except OSError as error:
                            result.add_error(f"{path}: {error}")
            except OSError as error:
                result.add_error(f"{folder}: {error}")
        return [files for files in sizes.values() if len(files) > 1]

    def hash_stage(self, buckets, function, label, result):
        output = []
        total = sum(map(len, buckets))
        done = 0
        self.report(label, 0, total, result, force=True)
        for files in buckets:
            grouped = defaultdict(list)
            for record in files:
                self.cancel.check()
                try:
                    grouped[function(record, self.cancel)].append(record)
                except OSError as error:
                    result.add_error(f"{record.path}: {error}")
                done += 1
                self.report(label, done, total, result, record.path)
            output.extend((digest, group) for digest, group in grouped.items() if len(group) > 1)
        return output

    def scan(self, root):
        root = Path(os.path.abspath(os.path.expanduser(root)))
        result = ScanResult()
        # Invalid top-level paths are fatal, distinct from inaccessible descendants.
        with directory_fd(root):
            pass
        try:
            self.report("Inventario", 0, 0, result, force=True)
            buckets = self.inventory(root, result)
            partial = self.hash_stage(buckets, partial_hash, "Hash parcial", result)
            complete = self.hash_stage([g for _, g in partial], full_hash, "Hash completo", result)
            total = sum(len(g) for _, g in complete)
            done = 0
            self.report("Verificación exacta", 0, total, result, force=True)
            for digest, files in complete:
                partitions = []
                for record in files:
                    self.cancel.check()
                    try:
                        current_stat(record)
                        for partition in partitions:
                            if identical(partition[0], record, self.cancel):
                                partition.append(record)
                                break
                        else:
                            partitions.append([record])
                    except OSError as error:
                        result.add_error(f"{record.path}: {error}")
                    done += 1
                    self.report("Verificación exacta", done, total, result, record.path)
                for partition in partitions:
                    # A representative may have disappeared during another comparison.
                    valid = []
                    for record in partition:
                        try:
                            current_stat(record)
                            valid.append(record)
                        except OSError as error:
                            result.add_error(str(error))
                    if len(valid) > 1:
                        result.groups.append(DuplicateGroup(len(result.groups) + 1, digest,
                                                           sorted(valid, key=lambda f: str(f.path))))
            self.report("Completado", total, total, result, force=True)
        except Cancelled:
            result.cancelled = True
            # A cancelled inventory/hash never exposes incomplete duplicate groups.
            result.groups.clear()
            self.report("Cancelado", 0, 0, result, force=True)
        return result
