# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated removal through either system trash or explicit permanent deletion."""
import os
import stat
from dataclasses import dataclass, field
from .hashing import Cancellation, Cancelled, FileChanged, current_stat, identical, directory_fd


@dataclass
class TrashReport:
    removed: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


def gio_trash(path):
    from gi.repository import Gio
    if not Gio.File.new_for_path(str(path)).trash(None):
        raise OSError("El sistema no pudo enviar el archivo a la papelera")


def permanent_delete(record):
    """Remove a verified regular file using a no-symlink parent descriptor."""
    with directory_fd(record.path.parent) as parent:
        current = os.stat(record.path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or not record.matches(current):
            raise FileChanged(f"Archivo modificado o sustituido: {record.path}")
        os.unlink(record.path.name, dir_fd=parent)


def trash_selected(result, cancel=None, trash=None, on_removed=None, on_progress=None, on_verifying=None):
    action = trash or gio_trash
    return _remove_selected(result, cancel, lambda record: action(record.path), on_removed, on_progress, on_verifying)


def delete_selected(result, cancel=None, delete=None, on_removed=None, on_progress=None, on_verifying=None):
    return _remove_selected(result, cancel, delete or permanent_delete, on_removed, on_progress, on_verifying)


def _remove_selected(result, cancel, remove, on_removed, on_progress, on_verifying):
    """Runs on a worker. Does not mutate the UI result model.

    Validate every member before starting a group. Before each trash, recheck
    remaining snapshots and compare the chosen target against a retained copy.
    A failure stops that group; other independent groups can still proceed.
    """
    cancel = cancel or Cancellation()
    on_removed = on_removed or (lambda path: None)
    on_progress = on_progress or (lambda done, total: None)
    report = TrashReport()
    selected = frozenset(result.selected)
    total = len(selected)
    done = 0
    try:
        for group in result.groups:
            cancel.check()
            targets = [f for f in group.files if f.path in selected]
            if not targets:
                continue
            keepers = [f for f in group.files if f.path not in selected]
            if not keepers:
                report.errors.append(f"Grupo {group.id}: debe conservar al menos una copia")
                continue
            keeper = keepers[0]
            remaining = list(group.files)
            try:
                for index, record in enumerate(remaining, 1):
                    cancel.check()
                    if on_verifying:
                        on_verifying(group.id, index, len(remaining), record.path)
                    current_stat(record)
                    if record != keeper and not identical(keeper, record, cancel):
                        raise FileChanged(f"El contenido ya no coincide: {record.path}")
                for target in targets:
                    cancel.check()
                    on_progress(done, total)
                    for record in remaining:
                        cancel.check()
                        current_stat(record)
                    if not identical(keeper, target, cancel):
                        raise FileChanged(f"El contenido ya no coincide: {target.path}")
                    # Final path checks immediately adjacent to the removal call.
                    current_stat(keeper)
                    current_stat(target)
                    cancel.check()
                    remove(target)
                    remaining.remove(target)
                    report.removed.append(target.path)
                    on_removed(target.path)
                    done += 1
                    on_progress(done, total)
            except Cancelled:
                raise
            except Exception as error:
                report.errors.append(f"Grupo {group.id}: {error}")
    except Cancelled:
        report.cancelled = True
    return report
