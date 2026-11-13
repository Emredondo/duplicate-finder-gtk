# SPDX-License-Identifier: GPL-3.0-or-later
"""Traditional GTK 3 UI. All GTK access is confined to the main thread."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import logging
import os
import queue
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from . import __version__, config
from .engine import Progress, ScanOptions, Scanner
from .hashing import Cancellation
from .model import ScanResult, automatic_selection
from .operations import trash_selected, delete_selected

LOG = logging.getLogger(__name__)


class FolderButton(Gtk.Button):
    """Open the full GTK folder browser directly, with no intermediate menu."""
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.filename = None
        box = Gtk.Box(spacing=6)
        box.pack_start(Gtk.Image.new_from_icon_name("folder-open", Gtk.IconSize.BUTTON), False, False, 0)
        self.label = Gtk.Label(label="Seleccionar carpeta…", xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        box.pack_start(self.label, True, True, 0)
        box.pack_end(Gtk.Label(label="Examinar…"), False, False, 0)
        self.add(box)
        self.connect("clicked", self.browse)

    def set_filename(self, filename):
        if not filename or not os.path.isdir(filename):
            return False
        self.filename = os.path.abspath(filename)
        self.label.set_text(display_path(self.filename))
        self.set_tooltip_text(display_path(self.filename))
        return True

    def get_filename(self):
        return self.filename

    def unselect_all(self):
        self.filename = None
        self.label.set_text("Seleccionar carpeta…")
        self.set_tooltip_text(None)

    def browse(self, *_):
        dialog = Gtk.FileChooserDialog(title=self.title, transient_for=self.get_toplevel(),
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Seleccionar", Gtk.ResponseType.ACCEPT)
        dialog.set_default_size(850, 600)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        dialog.set_current_folder(self.filename or str(Path.home()))
        dialog.connect("response", self._response)
        dialog.show_all()

    def _response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            self.set_filename(dialog.get_filename())
        dialog.destroy()


def display_path(path):
    # Linux permits non-UTF-8 names; GTK strings do not. Retain original paths in Python.
    return os.fsencode(path).decode("utf-8", "replace")


def human_size(size):
    amount = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if amount < 1024 or unit == "PiB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024


class Application(Gtk.Application):
    def __init__(self, folder=None):
        super().__init__(application_id="org.duplicatefinder.DuplicateFinderGTK",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.folder = folder
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self, self.folder)
        self.window.present()


class MainWindow(Gtk.ApplicationWindow):
    # selection, name, location, size, modified, group, id, selectable, tooltip
    TYPES = (bool, str, str, GObject.TYPE_UINT64, GObject.TYPE_DOUBLE, int, int, bool, str)

    def __init__(self, application, folder=None):
        super().__init__(application=application, title="Duplicate Finder GTK")
        self.set_icon_name("duplicate-finder-gtk")
        self.preferences = config.load()
        if folder:
            self.preferences["folder"] = os.path.abspath(os.path.expanduser(folder))
        self.set_default_size(self.preferences["width"], self.preferences["height"])
        if self.preferences["x"] is not None and self.preferences["y"] is not None:
            self.move(self.preferences["x"], self.preferences["y"])
        if self.preferences["maximized"]:
            self.maximize()
        self.result = ScanResult()
        self.records = {}
        self.path_ids = {}
        self.row_refs = {}
        self.events = queue.Queue()
        self.progress_lock = threading.Lock()
        self.latest_progress = None
        self.cancel_token = Cancellation()
        self.busy = False
        self.populating = False
        self.closing = False
        self._render_iterator = None
        self._build()
        self.connect("delete-event", self.on_close)
        self.connect("configure-event", self.on_configure)
        self.show_all()
        self.stack.set_visible_child_name(self.preferences["view"])
        self.update_summary("Listo para analizar")
        self.timer = GLib.timeout_add(100, self.poll)

    def _build(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(10)
        self.add(outer)
        # A standard desktop menu, independent from the toolbar.
        menubar = Gtk.MenuBar()
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label="Aplicación")
        item.set_submenu(menu)
        for label, callback in (("Restaurar preferencias", self.restore_defaults),
                                ("Acerca de", self.about), ("Salir", lambda *_: self.close())):
            action = Gtk.MenuItem(label=label)
            action.connect("activate", callback)
            menu.append(action)
        menubar.append(item)
        outer.pack_start(menubar, False, False, 0)
        toolbar = Gtk.Box(spacing=8)
        outer.pack_start(toolbar, False, False, 0)
        toolbar.pack_start(Gtk.Label(label="Carpeta:"), False, False, 0)
        self.folder_button = FolderButton("Seleccionar carpeta principal")
        self.folder_button.set_filename(self.preferences["folder"])
        self.folder_button.set_hexpand(True)
        toolbar.pack_start(self.folder_button, True, True, 0)
        self.scan_button = Gtk.Button.new_with_mnemonic("_Analizar")
        self.scan_button.connect("clicked", self.start_scan)
        toolbar.pack_start(self.scan_button, False, False, 0)
        self.cancel_button = Gtk.Button.new_with_mnemonic("_Cancelar")
        self.cancel_button.connect("clicked", self.cancel_job)
        self.cancel_button.set_sensitive(False)
        toolbar.pack_start(self.cancel_button, False, False, 0)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_text("Listo")
        outer.pack_start(self.progress, False, False, 0)
        self.current_path = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.current_path.set_max_width_chars(100)
        outer.pack_start(self.current_path, False, False, 0)

        panes = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        panes.set_position(275)
        outer.pack_start(panes, True, True, 0)
        scroll_side = Gtk.ScrolledWindow()
        scroll_side.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        panes.pack1(scroll_side, False, False)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.sidebar.set_border_width(8)
        self.sidebar.set_size_request(255, -1)
        scroll_side.add(self.sidebar)
        self.sidebar.pack_start(Gtk.Label(label="Opciones de búsqueda", xalign=0), False, False, 0)
        self.recursive = Gtk.CheckButton(label="Buscar en subcarpetas")
        self.recursive.set_active(self.preferences["recursive"])
        self.hidden = Gtk.CheckButton(label="Incluir archivos y carpetas ocultos")
        self.hidden.set_active(self.preferences["hidden"])
        self.sidebar.pack_start(self.recursive, False, False, 0)
        self.sidebar.pack_start(self.hidden, False, False, 0)
        self.sidebar.pack_start(Gtk.Label(label="Exclusiones (un patrón por línea):", xalign=0), False, False, 0)
        self.exclusions = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.exclusions.get_buffer().set_text(self.preferences["exclusions"])
        self.exclusions.set_tooltip_text("Patrones como *.tmp, cache o respaldo/*; se aplican al nombre y a la ruta relativa.")
        exclusions_scroll = Gtk.ScrolledWindow()
        exclusions_scroll.set_size_request(-1, 90)
        exclusions_scroll.add(self.exclusions)
        self.sidebar.pack_start(exclusions_scroll, False, False, 0)
        self.sidebar.pack_start(Gtk.Separator(), False, False, 0)
        self.sidebar.pack_start(Gtk.Label(label="Conservar una copia", xalign=0), False, False, 0)
        self.criterion = Gtk.ComboBoxText()
        for key, label in (("oldest", "El archivo más antiguo"), ("newest", "El archivo más reciente"),
                           ("priority", "Priorizar una carpeta")):
            self.criterion.append(key, label)
        self.criterion.set_active_id(self.preferences["criterion"])
        self.sidebar.pack_start(self.criterion, False, False, 0)
        self.sidebar.pack_start(Gtk.Label(label="Carpeta prioritaria:", xalign=0), False, False, 0)
        self.priority = FolderButton("Seleccionar carpeta prioritaria")
        if self.preferences["priority"]:
            self.priority.set_filename(self.preferences["priority"])
        self.priority.set_tooltip_text("Se conserva el más antiguo dentro de esta carpeta o sus subcarpetas.")
        self.sidebar.pack_start(self.priority, False, False, 0)
        self.auto_button = Gtk.Button(label="Seleccionar duplicados\nautomáticamente")
        self.auto_button.connect("clicked", self.auto_select)
        self.sidebar.pack_start(self.auto_button, False, False, 0)
        self.clear_button = Gtk.Button(label="Quitar toda la selección")
        self.clear_button.connect("clicked", self.clear_selection)
        self.sidebar.pack_start(self.clear_button, False, False, 0)
        note = Gtk.Label(label="Los resultados aparecen sin marcar.\nSiempre se conserva al menos una copia.",
                         xalign=0, wrap=True)
        note.get_style_context().add_class("dim-label")
        self.sidebar.pack_start(note, False, False, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panes.pack2(main, True, False)
        modes = Gtk.Box(spacing=6)
        main.pack_start(modes, False, False, 0)
        self.stack = Gtk.Stack()
        switcher = Gtk.StackSwitcher(stack=self.stack)
        modes.pack_start(switcher, False, False, 0)
        self.delete_button = Gtk.Button(label="Eliminar definitivamente…")
        self.delete_button.get_style_context().add_class("destructive-action")
        self.delete_button.connect("clicked", self.confirm_delete)
        modes.pack_end(self.delete_button, False, False, 0)
        self.trash_button = Gtk.Button(label="Enviar selección a la papelera…")
        self.trash_button.connect("clicked", self.confirm_trash)
        modes.pack_end(self.trash_button, False, False, 0)
        self.tree_store = Gtk.TreeStore(*self.TYPES)
        self.table_store = Gtk.ListStore(*self.TYPES)
        self.views = {}
        self.columns = {}
        for mode, title, store in (("tree", "Árbol", self.tree_store), ("table", "Tabla", self.table_store)):
            view = Gtk.TreeView(model=store)
            view.set_headers_visible(True)
            view.set_enable_search(True)
            view.set_search_column(1)
            view.set_tooltip_column(8)
            view.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
            toggle = Gtk.CellRendererToggle()
            toggle.connect("toggled", self.on_toggle, mode)
            column = Gtk.TreeViewColumn("Eliminar", toggle, active=0, activatable=7, visible=7)
            self.add_column(view, mode, column, 0, 78)
            for index, label, width in ((1, "Nombre", 220), (2, "Ubicación", 300),
                                         (3, "Tamaño", 100), (4, "Modificación", 155), (5, "Grupo", 80)):
                renderer = Gtk.CellRendererText()
                if index in (1, 2):
                    renderer.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
                column = Gtk.TreeViewColumn(label, renderer)
                if index in (3, 4, 5):
                    column.set_cell_data_func(renderer, self.format_cell, index)
                else:
                    column.add_attribute(renderer, "text", index)
                column.set_sort_column_id(index)
                self.add_column(view, mode, column, index, width)
            view.connect("row-activated", self.on_row_activated)
            view.connect("button-press-event", self.on_context_menu)
            view.connect("popup-menu", self.on_keyboard_menu)
            self.views[mode] = view
            scroll = Gtk.ScrolledWindow()
            scroll.add(view)
            self.stack.add_titled(scroll, mode, title)
        main.pack_start(self.stack, True, True, 0)
        self.summary = Gtk.Label(xalign=0, wrap=True)
        outer.pack_start(self.summary, False, False, 0)
        bottom = Gtk.Box(spacing=8)
        self.status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        bottom.pack_start(self.status, True, True, 0)
        self.error_button = Gtk.Button(label="Ver incidencias")
        self.error_button.connect("clicked", self.show_errors)
        bottom.pack_end(self.error_button, False, False, 0)
        outer.pack_start(bottom, False, False, 0)

    def add_column(self, view, mode, column, index, default):
        column.set_resizable(True)
        column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column.set_fixed_width(self.preferences["columns"].get(f"{mode}:{index}", default))
        view.append_column(column)
        self.columns[(mode, index)] = column

    @staticmethod
    def format_cell(column, renderer, model, tree_iter, index):
        value = model.get_value(tree_iter, index)
        if index == 3:
            text = human_size(value)
        elif index == 4:
            try:
                text = (datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
                        if model.get_value(tree_iter, 7) else "")
            except (OverflowError, OSError, ValueError):
                text = "Fecha fuera de rango"
        else:
            text = str(value)
        renderer.set_property("text", text)

    def notice(self, title, text, error=False):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                                   buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(display_path(str(text)))
        dialog.run()
        dialog.destroy()

    def post_progress(self, progress):
        with self.progress_lock:
            self.latest_progress = progress

    def set_busy(self, busy):
        self.busy = busy
        self.folder_button.set_sensitive(not busy)
        self.scan_button.set_sensitive(not busy and not self.populating)
        self.sidebar.set_sensitive(not busy and not self.populating)
        self.cancel_button.set_sensitive(busy)
        self.update_summary()

    def launch(self, job):
        self.cancel_token = Cancellation()
        self.set_busy(True)

        def run():
            try:
                job()
            except Exception as error:
                LOG.exception("Falló una operación")
                self.events.put(("failure", str(error)))
        threading.Thread(target=run, name="duplicate-finder-worker", daemon=False).start()

    def start_scan(self, *_):
        if self.busy or self.populating:
            return
        folder = self.folder_button.get_filename()
        if not folder:
            self.notice("Seleccione una carpeta", "Elija la carpeta que desea analizar.")
            return
        buffer = self.exclusions.get_buffer()
        exclusions = tuple(line.strip() for line in buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True).splitlines() if line.strip())
        options = ScanOptions(self.recursive.get_active(), self.hidden.get_active(), exclusions)
        self.result = ScanResult()
        self.clear_models()
        self.progress.set_fraction(0)
        self.update_summary("Analizando…")

        def job():
            scanner = Scanner(options, self.cancel_token, self.post_progress)
            result = scanner.scan(folder)
            self.events.put(("scan_done", result))
        self.launch(job)

    def cancel_job(self, *_):
        self.cancel_token.cancel()
        self.cancel_button.set_sensitive(False)
        self.status.set_text("Cancelando al terminar el bloque actual…")

    def poll(self):
        with self.progress_lock:
            progress, self.latest_progress = self.latest_progress, None
        if progress:
            self.progress.set_text(progress.stage)
            if progress.total:
                self.progress.set_fraction(min(1, progress.done / progress.total))
            elif self.busy:
                self.progress.pulse()
            self.current_path.set_text(display_path(progress.path))
            if progress.stage == "Inventario":
                self.summary.set_text(f"Archivos examinados: {progress.examined:,}")
        for _ in range(200):
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "scan_done":
                self.result = payload
                self.set_busy(False)
                self.render_results()
                self.progress.set_fraction(0 if payload.cancelled else 1)
                self.progress.set_text("Cancelado" if payload.cancelled else "Completado")
                self.current_path.set_text("")
                self.update_summary("Análisis cancelado" if payload.cancelled else "Análisis completado")
            elif kind == "removed":
                self.result.remove(payload)
                self.remove_row(payload)
                self.update_summary("Procesando archivos…")
            elif kind in ("trash_done", "delete_done"):
                self.result.errors.extend(payload.errors[:max(0, 500 - len(self.result.errors))])
                self.result.error_count += len(payload.errors)
                self.set_busy(False)
                self.render_results()
                destination = "eliminado(s) definitivamente" if kind == "delete_done" else "en la papelera"
                self.update_summary(f"Operación {'cancelada' if payload.cancelled else 'completada'}: {len(payload.removed)} archivo(s) {destination}")
                self.progress.set_text("Cancelado" if payload.cancelled else "Completado")
                if payload.errors:
                    self.notice("Algunos grupos no se pudieron procesar", "\n".join(payload.errors[:15]), True)
            elif kind == "failure":
                self.set_busy(False)
                self.progress.set_text("Error")
                self.update_summary("Operación interrumpida")
                self.notice("No se pudo completar la operación", payload, True)
        if self.closing and not self.busy and not self.populating:
            self.persist()
            self.destroy()
            return False
        return True

    def clear_models(self):
        self.tree_store.clear()
        self.table_store.clear()
        self.records.clear()
        self.path_ids.clear()
        self.row_refs.clear()

    def render_results(self):
        self.clear_models()
        self.populating = True
        self.set_busy(self.busy)
        self._render_iterator = self.result_rows()
        GLib.idle_add(self.render_chunk)

    def result_rows(self):
        row_id = 0
        for group in self.result.groups:
            parent = self.tree_store.append(None, [False, f"Grupo {group.id} — {len(group.files)} archivos",
                                                  "", group.files[0].size, 0, group.id, 0, False, group.digest])
            for record in group.files:
                row_id += 1
                self.records[row_id] = record
                self.path_ids[record.path] = row_id
                tooltip = display_path(record.path)
                if record.nlink > 1:
                    tooltip += f"\n{record.nlink} enlaces duros; espacio estimado recuperable: 0 B"
                row = [record.path in self.result.selected, display_path(record.path.name),
                       display_path(record.path.parent), record.size, record.mtime_ns / 1_000_000_000,
                       group.id, row_id, True, tooltip]
                ti = self.tree_store.append(parent, row)
                li = self.table_store.append(row)
                self.row_refs[row_id] = (
                    Gtk.TreeRowReference.new(self.tree_store, self.tree_store.get_path(ti)),
                    Gtk.TreeRowReference.new(self.table_store, self.table_store.get_path(li)))
                yield

    def render_chunk(self):
        try:
            for _ in range(150):
                next(self._render_iterator)
        except StopIteration:
            self.populating = False
            self._render_iterator = None
            if len(self.result.groups) <= 100:
                self.views["tree"].expand_all()
            self.set_busy(self.busy)
            return False
        return True

    def remove_row(self, path):
        row_id = self.path_ids.get(path)
        if row_id is None:
            return
        for store, ref in zip((self.tree_store, self.table_store), self.row_refs.get(row_id, ())):
            if ref.valid():
                store.remove(store.get_iter(ref.get_path()))
        self.records.pop(row_id, None)
        self.row_refs.pop(row_id, None)
        self.path_ids.pop(path, None)
        # Remove now-singleton groups from the displayed duplicate results.
        active = {f.path for g in self.result.groups for f in g.files}
        for candidate in list(self.path_ids):
            if candidate not in active:
                rid = self.path_ids.pop(candidate)
                for store, ref in zip((self.tree_store, self.table_store), self.row_refs.pop(rid, ())):
                    if ref.valid():
                        store.remove(store.get_iter(ref.get_path()))
                self.records.pop(rid, None)
        node = self.tree_store.get_iter_first()
        while node is not None:
            following = self.tree_store.iter_next(node)
            count = self.tree_store.iter_n_children(node)
            if count == 0:
                self.tree_store.remove(node)
            else:
                self.tree_store.set_value(node, 1, f"Grupo {self.tree_store.get_value(node, 5)} — {count} archivos")
            node = following

    def sync_selection(self, paths=None):
        ids = list(self.row_refs) if paths is None else [self.path_ids[p] for p in paths if p in self.path_ids]

        def rows():
            for row_id in ids:
                record = self.records[row_id]
                for store, ref in zip((self.tree_store, self.table_store), self.row_refs[row_id]):
                    if ref.valid():
                        store.set_value(store.get_iter(ref.get_path()), 0, record.path in self.result.selected)
                yield

        iterator = rows()
        if len(ids) <= 300:
            for _ in iterator:
                pass
            self.update_summary()
            return
        self.populating = True
        self.set_busy(self.busy)

        def chunk():
            try:
                for _ in range(150):
                    next(iterator)
            except StopIteration:
                self.populating = False
                self.set_busy(self.busy)
                return False
            return True
        GLib.idle_add(chunk)
        self.update_summary()

    def change_selection(self, record, selected):
        if self.busy or self.populating:
            return
        if not self.result.set_selected(record.path, selected):
            self.notice("Debe conservar una copia", "Quite la marca de otra copia antes de seleccionar este archivo.")
        self.sync_selection((record.path,))

    def on_toggle(self, renderer, path, mode):
        model = self.views[mode].get_model()
        tree_iter = model.get_iter(path)
        record = self.records.get(model.get_value(tree_iter, 6))
        if record:
            self.change_selection(record, record.path not in self.result.selected)

    def auto_select(self, *_):
        if self.busy or self.populating:
            return
        try:
            automatic_selection(self.result, self.criterion.get_active_id(), self.priority.get_filename())
            self.sync_selection()
        except ValueError as error:
            self.notice("Falta una carpeta prioritaria", str(error))

    def clear_selection(self, *_):
        if not self.busy and not self.populating:
            self.result.selected.clear()
            self.sync_selection()

    def update_summary(self, state=None):
        r = self.result
        self.summary.set_text(
            f"Examinados: {r.examined:,}   |   Grupos: {len(r.groups):,}   |   Copias redundantes: {r.redundant_count:,}\n"
            f"Recuperable al quitar copias: {human_size(r.potential_bytes)}   |   Selección: {len(r.selected):,} archivos · {human_size(r.selected_bytes)}")
        self.trash_button.set_sensitive(bool(r.selected) and not self.busy and not self.populating)
        self.delete_button.set_sensitive(bool(r.selected) and not self.busy and not self.populating)
        self.error_button.set_sensitive(bool(r.error_count))
        self.auto_button.set_sensitive(bool(r.groups))
        self.clear_button.set_sensitive(bool(r.selected))
        if state:
            suffix = f" · {r.error_count} incidencias" if r.error_count else ""
            self.status.set_text(state + suffix)

    def confirm_trash(self, *_):
        if self.busy or self.populating or not self.result.selected:
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text="¿Enviar la selección a la papelera?")
        dialog.format_secondary_text(
            f"{len(self.result.selected)} archivo(s) · {human_size(self.result.selected_bytes)} estimados.\n\n"
            "Se verificará el contenido otra vez y se conservará al menos una copia por grupo. "
            "Puede recuperar los archivos desde la papelera. El espacio en disco se libera al vaciarla.")
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("Enviar a la papelera", Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        # The worker gets independent lists and selection, never a mutable UI model.
        snapshot = deepcopy(self.result)

        def job():
            report = trash_selected(snapshot, self.cancel_token,
                                    on_removed=lambda path: self.events.put(("removed", path)),
                                    on_progress=lambda done, total: self.post_progress(
                                        Progress("Verificando y enviando a la papelera", done, total, snapshot.examined)))
            self.events.put(("trash_done", report))
        self.launch(job)
        self.update_summary("Verificando contenido antes de enviar a la papelera…")

    def confirm_delete(self, *_):
        if self.busy or self.populating or not self.result.selected:
            return
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE, text="¿Está seguro?")
        dialog.format_secondary_text(
            f"Se eliminarán definitivamente {len(self.result.selected)} archivo(s) "
            f"({human_size(self.result.selected_bytes)} estimados).\n\n"
            "No pasarán por la papelera y no se podrán recuperar desde ella. "
            "Se comprobará el contenido y se conservará al menos una copia por grupo.")
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("OK", Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        snapshot = deepcopy(self.result)

        def job():
            report = delete_selected(snapshot, self.cancel_token,
                                     on_removed=lambda path: self.events.put(("removed", path)),
                                     on_progress=lambda done, total: self.post_progress(
                                         Progress("Verificando y eliminando definitivamente", done, total, snapshot.examined)))
            self.events.put(("delete_done", report))
        self.launch(job)
        self.update_summary("Verificando antes de eliminar definitivamente…")

    def selected_record(self, view):
        model, tree_iter = view.get_selection().get_selected()
        return self.records.get(model.get_value(tree_iter, 6)) if tree_iter is not None else None

    def on_row_activated(self, view, path, column):
        record = self.records.get(view.get_model()[path][6])
        if record:
            self.open_file(record)

    def on_context_menu(self, view, event):
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        view.set_cursor(hit[0])
        return self.context_menu(view, event)

    def on_keyboard_menu(self, view):
        return self.context_menu(view, None)

    def context_menu(self, view, event):
        record = self.selected_record(view)
        if not record:
            return False
        menu = Gtk.Menu()
        for label, callback in (("Abrir archivo", self.open_file), ("Abrir con otra aplicación…", self.open_with),
                                ("Mostrar en carpeta", self.show_in_folder), ("Copiar ruta completa", self.copy_path),
                                ("Ver propiedades", self.properties)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _, cb=callback: cb(record))
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        for label, selected in (("Seleccionar para eliminación", True), ("Quitar de la selección", False)):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(not self.busy and not self.populating)
            item.connect("activate", lambda _, value=selected: self.change_selection(record, value))
            menu.append(item)
        menu.show_all()
        if event:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(view, Gdk.Gravity.CENTER, Gdk.Gravity.CENTER, None)
        return True

    def open_file(self, record):
        uri = Gio.File.new_for_path(str(record.path)).get_uri()
        Gio.AppInfo.launch_default_for_uri_async(uri, self.get_display().get_app_launch_context(),
                                                None, self.launch_finished, None)

    def launch_finished(self, source, result, data):
        try:
            Gio.AppInfo.launch_default_for_uri_finish(result)
        except GLib.Error as error:
            self.notice("No se pudo abrir", error.message, True)

    def open_with(self, record):
        dialog = Gtk.AppChooserDialog.new(self, Gtk.DialogFlags.MODAL,
                                          Gio.File.new_for_path(str(record.path)))
        dialog.set_heading("Seleccione una aplicación para abrir el archivo")
        dialog.get_widget().set_show_other(True)
        if dialog.run() == Gtk.ResponseType.OK:
            app = dialog.get_app_info()
            if app:
                try:
                    app.launch([Gio.File.new_for_path(str(record.path))], self.get_display().get_app_launch_context())
                except GLib.Error as error:
                    self.notice("No se pudo abrir", error.message, True)
        dialog.destroy()

    def show_in_folder(self, record):
        # Async D-Bus call, with async folder launch as a desktop-independent fallback.
        uri = Gio.File.new_for_path(str(record.path)).get_uri()

        def connected(source, result, data):
            try:
                bus = Gio.bus_get_finish(result)
                bus.call("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                         "org.freedesktop.FileManager1", "ShowItems", GLib.Variant("(ass)", ([uri], "")),
                         None, Gio.DBusCallFlags.NONE, 3000, None, shown, None)
            except GLib.Error:
                fallback()

        def shown(bus, result, data):
            try:
                bus.call_finish(result)
            except GLib.Error:
                fallback()

        def fallback():
            Gio.AppInfo.launch_default_for_uri_async(Gio.File.new_for_path(str(record.path.parent)).get_uri(),
                                                    self.get_display().get_app_launch_context(), None,
                                                    self.launch_finished, None)
        Gio.bus_get(Gio.BusType.SESSION, None, connected, None)

    def copy_path(self, record):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(display_path(record.path), -1)

    def properties(self, record):
        # Snapshot properties need no blocking disk reads on the GTK thread.
        content_type, _ = Gio.content_type_guess(str(record.path), None)
        text = (f"Nombre: {display_path(record.path.name)}\nUbicación: {display_path(record.path.parent)}\n"
                f"Tamaño: {human_size(record.size)} ({record.size:,} bytes)\n"
                f"Modificación: {datetime.fromtimestamp(record.mtime_ns / 1_000_000_000)}\n"
                f"Tipo: {Gio.content_type_get_description(content_type)}\n"
                f"Dispositivo: {record.device} · Inodo: {record.inode}\nEnlaces duros: {record.nlink}\n\n"
                "Metadatos registrados durante el análisis. Se revalidan antes de enviar a la papelera.")
        self.notice("Propiedades del archivo", text)

    def show_errors(self, *_):
        dialog = Gtk.Dialog(title="Incidencias del análisis y la papelera", transient_for=self, modal=True)
        dialog.add_button("Cerrar", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(700, 400)
        text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        text.get_buffer().set_text(display_path("\n\n".join(self.result.errors)) +
                                   f"\n\nTotal: {self.result.error_count}. Se muestran hasta 500 incidencias.\n"
                                   f"Nombres de enlaces duros omitidos: {self.result.hardlinks_skipped}. "
                                   f"Enlaces simbólicos omitidos: {self.result.symlinks_skipped}.")
        scroll = Gtk.ScrolledWindow()
        scroll.add(text)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def restore_defaults(self, *_):
        if self.busy or self.populating:
            self.notice("Operación en curso", "Espere a que finalice antes de restaurar las preferencias.")
            return
        self.preferences = deepcopy(config.DEFAULTS)
        self.folder_button.set_filename(self.preferences["folder"])
        self.recursive.set_active(True)
        self.hidden.set_active(False)
        self.exclusions.get_buffer().set_text(self.preferences["exclusions"])
        self.criterion.set_active_id("oldest")
        self.priority.unselect_all()
        self.stack.set_visible_child_name("tree")
        for (mode, index), column in self.columns.items():
            column.set_fixed_width({0: 78, 1: 220, 2: 300, 3: 100, 4: 155, 5: 80}[index])
        self.unmaximize()
        self.resize(1120, 720)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.persist()
        self.update_summary("Preferencias predeterminadas restauradas")

    def about(self, *_):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True, program_name="Duplicate Finder GTK",
                                 version=__version__, logo_icon_name="duplicate-finder-gtk",
                                 comments="Encuentra duplicados por igualdad exacta de contenido.\nSin nube ni telemetría.",
                                 license_type=Gtk.License.GPL_3_0, copyright="© 2026 Duplicate Finder GTK contributors")
        dialog.run()
        dialog.destroy()

    def on_configure(self, widget, event):
        if not self.is_maximized():
            self.preferences.update(width=event.width, height=event.height, x=event.x, y=event.y)
        return False

    def persist(self):
        buffer = self.exclusions.get_buffer()
        self.preferences.update(
            folder=self.folder_button.get_filename() or self.preferences["folder"],
            view=self.stack.get_visible_child_name(), maximized=self.is_maximized(),
            recursive=self.recursive.get_active(), hidden=self.hidden.get_active(),
            criterion=self.criterion.get_active_id(), priority=self.priority.get_filename() or "",
            exclusions=buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True),
            columns={f"{mode}:{index}": max(45, col.get_width()) for (mode, index), col in self.columns.items()})
        try:
            config.save(self.preferences)
        except OSError as error:
            LOG.warning("No se pudieron guardar preferencias: %s", error)

    def on_close(self, *_):
        if self.busy or self.populating:
            self.closing = True
            self.cancel_job()
            self.set_sensitive(False)
            return True
        self.persist()
        GLib.source_remove(self.timer)
        return False
