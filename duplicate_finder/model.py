# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass(frozen=True)
class FileRecord:
    path: Path
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int
    nlink: int

    @classmethod
    def from_stat(cls, path, st):
        return cls(Path(path), st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                   st.st_dev, st.st_ino, st.st_nlink)

    def matches(self, st):
        return self == self.from_stat(self.path, st)

    @property
    def reclaimable(self):
        # Other names still point to a multiply-linked inode. Do not promise space.
        return self.size if self.nlink == 1 else 0


@dataclass
class DuplicateGroup:
    id: int
    digest: str
    files: list[FileRecord]


@dataclass
class ScanResult:
    groups: list[DuplicateGroup] = field(default_factory=list)
    examined: int = 0
    hardlinks_skipped: int = 0
    symlinks_skipped: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    selected: set[Path] = field(default_factory=set)

    def add_error(self, message):
        self.error_count += 1
        if len(self.errors) < 500:
            self.errors.append(str(message))

    @property
    def redundant_count(self):
        return sum(len(g.files) - 1 for g in self.groups)

    @property
    def potential_bytes(self):
        return sum(sum(f.reclaimable for f in g.files) -
                   min(f.reclaimable for f in g.files) for g in self.groups)

    @property
    def selected_bytes(self):
        return sum(f.reclaimable for g in self.groups for f in g.files
                   if f.path in self.selected)

    def set_selected(self, path, selected):
        path = Path(path)
        for group in self.groups:
            if any(f.path == path for f in group.files):
                if selected:
                    if all(f.path == path or f.path in self.selected for f in group.files):
                        return False
                    self.selected.add(path)
                else:
                    self.selected.discard(path)
                return True
        return False

    def remove(self, path):
        path = Path(path)
        self.selected.discard(path)
        for group in self.groups:
            group.files[:] = [f for f in group.files if f.path != path]
        surviving = []
        for group in self.groups:
            if len(group.files) > 1:
                surviving.append(group)
            else:
                for f in group.files:
                    self.selected.discard(f.path)
        self.groups[:] = surviving


def automatic_selection(result, criterion="oldest", priority=None):
    if criterion not in ("oldest", "newest", "priority"):
        raise ValueError("Criterio de conservación desconocido")
    priority = Path(os.path.abspath(priority)) if priority else None
    if criterion == "priority" and priority is None:
        raise ValueError("Seleccione una carpeta prioritaria")
    selected = set()
    for group in result.groups:
        candidates = group.files
        if criterion == "priority":
            preferred = [f for f in candidates if f.path.is_relative_to(priority)]
            candidates = preferred or candidates
        key = lambda f: (f.mtime_ns, str(f.path))
        keeper = max(candidates, key=key) if criterion == "newest" else min(candidates, key=key)
        selected.update(f.path for f in group.files if f != keeper)
    result.selected = selected
