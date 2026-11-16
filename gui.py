"""GTK4 + libadwaita window: browse collections, search images and configure wallpapers."""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from bing_images import SIZES as BING_SIZES, BingImage, search as bing_search
from config import Collection, Config, State, cache_dir, config_dir
from collection_ops import rename_collection, remove_collection, validate_name, copy_image
from image_sources import API_SIZES, search as catalog_search
from ddg_images import SIZES as DDG_SIZES, DdgImage, search as ddg_search
from rotator import EXTS as IMAGE_EXTS, list_images, pick_random
from wallpaper import compose_and_apply

THUMB_W = 220
THUMB_H = 138


def _thumb_dir() -> Path:
    d = cache_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_thumb(src: Path) -> Path:
    """Pillow-cached thumbnail keyed by (path, mtime)."""
    from PIL import Image
    key = f"{src}:{src.stat().st_mtime_ns}".encode()
    h = hashlib.md5(key).hexdigest()[:12]
    dest = _thumb_dir() / f"{h}.jpg"
    if dest.exists():
        return dest
    img = Image.open(src).convert("RGB")
    img.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
    img.save(dest, "JPEG", quality=80)
    return dest


def _picture_from_file(path: Path) -> Gtk.Picture:
    pic = Gtk.Picture.new_for_filename(str(path))
    pic.set_size_request(THUMB_W, THUMB_H)
    pic.set_content_fit(Gtk.ContentFit.COVER)
    return pic


class LingoWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Lingo")
        self.set_default_size(1100, 720)

        self.cfg = Config.load()
        self.state = State.load()

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(240)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)
        toolbar.set_content(paned)

        paned.set_start_child(self._build_sidebar())
        paned.set_end_child(self.view_stack)

        self.view_stack.add_titled_with_icon(
            self._build_browse_tab(), "browse", "Browse", "folder-pictures-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_ddg_tab(), "ddg", "Search", "edit-find-symbolic"
        )

        self.view_stack.add_titled_with_icon(
            self._build_settings_tab(), "settings", "Settings", "preferences-system-symbolic"
        )
        self._refresh_collections()
        self._refresh_browse()
        keys = Gtk.EventControllerKey.new()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

    # ---------- sidebar ----------

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        label = Gtk.Label(label="Collections", xalign=0)
        label.add_css_class("title-4")
        box.append(label)

        self.coll_list = Gtk.ListBox()
        self.coll_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.coll_list.connect("row-selected", self._on_collection_selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self.coll_list)
        box.append(scroll)

        new_btn = Gtk.Button(label="+ New collection")
        new_btn.connect("clicked", self._on_new_collection_clicked)
        box.append(new_btn)

        return box

    def _refresh_collections(self) -> None:
        child = self.coll_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.coll_list.remove(child)
            child = nxt

        active_row: Gtk.ListBoxRow | None = None
        for name, coll in self.cfg.collections.items():
            row = Gtk.ListBoxRow()
            row.coll_name = name  # type: ignore[attr-defined]
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hb.set_margin_top(6)
            hb.set_margin_bottom(6)
            hb.set_margin_start(8)
            hb.set_margin_end(8)
            icon = Gtk.Image.new_from_icon_name("folder-symbolic")
            hb.append(icon)
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            title = Gtk.Label(label=name, xalign=0)
            title.add_css_class("heading")
            count = len(list_images(coll.path))
            subtitle = Gtk.Label(label=f"{count} images", xalign=0)
            subtitle.add_css_class("caption")
            subtitle.add_css_class("dim-label")
            vb.append(title)
            vb.append(subtitle)
            hb.append(vb)
            row.set_child(hb)
            gesture = Gtk.GestureClick.new()
            gesture.set_button(3)
            gesture.connect("pressed", self._on_collection_menu, row, name)
            row.add_controller(gesture)
            self.coll_list.append(row)
            if name == self.cfg.active_collection:
                active_row = row
        if active_row is not None:
            self.coll_list.select_row(active_row)

        self._update_ddg_dropdown()

    def _on_collection_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        name = getattr(row, "coll_name", None)
        if name is None or name == self.cfg.active_collection:
            self._refresh_browse()
            return
        self.cfg.active_collection = name
        self.cfg.save()
        self._toast(f"Switched to {name}")
        self._refresh_browse()

    def _on_new_collection_clicked(self, _btn: Gtk.Button) -> None:
        dialog = Adw.MessageDialog.new(self, "New collection", None)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        entry = Gtk.Entry(placeholder_text="collection name, e.g. landscapes")
        dialog.set_extra_child(entry)
        dialog.connect("response", self._on_new_collection_response, entry)
        dialog.present()

    def _on_new_collection_response(
        self, dialog: Adw.MessageDialog, response: str, entry: Gtk.Entry
    ) -> None:
        if response != "create":
            return
        name = entry.get_text().strip()
        try:
            validate_name(self.cfg, name)
        except ValueError as e:
            self._toast(str(e))
            return
        path = config_dir() / name
        path.mkdir(parents=True, exist_ok=True)
        self.cfg.collections[name] = Collection(name=name, path=path)
        self.cfg.save()
        self._refresh_collections()
        self._toast(f"Created {name} at {path}")

    def _on_collection_menu(self, gesture, _press, x, y, row, name) -> None:
        popover = Gtk.Popover()
        popover.set_parent(row)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for label, callback in (("Rename collection…", self._rename_collection),
                                ("Delete collection…", self._delete_collection)):
            button = Gtk.Button(label=label)
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, fn=callback: (popover.popdown(), fn(name)))
            box.append(button)
        popover.set_child(box)
        popover.connect("closed", lambda widget: widget.unparent())
        popover.popup()

    def _rename_collection(self, name: str) -> None:
        dialog = Adw.MessageDialog.new(self, "Rename collection", None)
        entry = Gtk.Entry(text=name)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("rename", "Rename")
        dialog.set_default_response("rename")
        def response(_dialog, action):
            if action != "rename":
                return
            try:
                rename_collection(self.cfg, self.state, name, entry.get_text().strip())
                self.cfg.save()
                self.state.save()
            except (ValueError, OSError) as e:
                self._toast(str(e))
                return
            self._refresh_collections()
            self._refresh_browse()
        dialog.connect("response", response)
        dialog.present()

    def _delete_collection(self, name: str) -> None:
        dialog = Adw.MessageDialog.new(self, "Delete collection?",
            f'Remove “{name}” from Lingo? Image files will remain in {self.cfg.collections[name].path}.')
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        def response(_dialog, action):
            if action != "delete":
                return
            try:
                remove_collection(self.cfg, self.state, name)
                self.cfg.save()
                self.state.save()
            except (ValueError, OSError) as e:
                self._toast(str(e))
                return
            self._refresh_collections()
            self._refresh_browse()
        dialog.connect("response", response)
        dialog.present()

    # ---------- browse tab ----------

    def _build_browse_tab(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.set_margin_top(10)
        bar.set_margin_bottom(4)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.set_label("Add images…")
        add_btn.set_always_show_image(True) if hasattr(add_btn, "set_always_show_image") else None
        add_btn.connect("clicked", self._on_add_images_clicked)
        bar.append(add_btn)

        import_folder_btn = Gtk.Button(label="Import folder…")
        import_folder_btn.connect("clicked", self._on_import_folder_clicked)
        bar.append(import_folder_btn)
        for label, tooltip, callback in (
            ("go-previous-symbolic", "Previous wallpaper (Alt+Left)", lambda _b: self._navigate_wallpaper(False)),
            ("go-next-symbolic", "Next wallpaper (Alt+Right)", lambda _b: self._navigate_wallpaper(True)),
            ("view-refresh-symbolic", "Refresh collection (Ctrl+R)", lambda _b: self._refresh_collections()),
            ("folder-open-symbolic", "Open collection folder", self._open_collection_folder),
        ):
            button = Gtk.Button.new_from_icon_name(label)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", callback)
            bar.append(button)

        self.browse_label = Gtk.Label(label="", xalign=0)
        self.browse_label.add_css_class("dim-label")
        self.browse_label.set_hexpand(True)
        bar.append(self.browse_label)

        outer.append(bar)

        self.browse_flow = Gtk.FlowBox()
        self.browse_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.browse_flow.set_max_children_per_line(6)
        self.browse_flow.set_column_spacing(12)
        self.browse_flow.set_row_spacing(12)
        self.browse_flow.set_margin_top(8)
        self.browse_flow.set_margin_bottom(12)
        self.browse_flow.set_margin_start(12)
        self.browse_flow.set_margin_end(12)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self.browse_flow)
        outer.append(scroll)
        return outer

    def _refresh_browse(self) -> None:
        child = self.browse_flow.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.browse_flow.remove(child)
            child = nxt

        coll = self.cfg.active()
        images = list_images(coll.path)
        if hasattr(self, "browse_label"):
            self.browse_label.set_label(f"{coll.name} · {len(images)} images · {coll.path}")
        if not images:
            empty = Gtk.Label(label=f"No images in {coll.path}")
            empty.add_css_class("dim-label")
            self.browse_flow.append(empty)
            return
        for img_path in images:
            try:
                thumb = _make_thumb(img_path)
            except Exception:
                continue
            card = Gtk.Button()
            card.add_css_class("flat")
            card.connect("clicked", self._on_image_clicked, img_path)
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vb.append(_picture_from_file(thumb))
            name = img_path.name
            if len(name) > 30:
                name = name[:27] + "…"
            lbl = Gtk.Label(label=name)
            lbl.add_css_class("caption")
            lbl.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            vb.append(lbl)
            card.set_child(vb)

            overlay = Gtk.Overlay()
            overlay.set_child(card)
            delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            delete_btn.add_css_class("circular")
            delete_btn.add_css_class("osd")
            delete_btn.set_tooltip_text("Delete this wallpaper")
            delete_btn.set_halign(Gtk.Align.END)
            delete_btn.set_valign(Gtk.Align.START)
            delete_btn.set_margin_top(6)
            delete_btn.set_margin_end(6)
            delete_btn.connect("clicked", self._on_delete_clicked, img_path)
            overlay.add_overlay(delete_btn)
            copy_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
            copy_btn.add_css_class("circular")
            copy_btn.add_css_class("osd")
            copy_btn.set_tooltip_text("Copy to another collection…")
            copy_btn.set_halign(Gtk.Align.START)
            copy_btn.set_valign(Gtk.Align.START)
            copy_btn.set_margin_top(6)
            copy_btn.set_margin_start(6)
            copy_btn.connect("clicked", self._on_copy_image, img_path)
            overlay.add_overlay(copy_btn)
            self.browse_flow.append(overlay)

    def _on_copy_image(self, _button, image_path: Path) -> None:
        names = [name for name, coll in self.cfg.collections.items()
                 if coll.path.resolve() != image_path.parent.resolve()]
        if not names:
            self._toast("Create another collection first")
            return
        dialog = Adw.MessageDialog.new(self, "Copy image to collection", image_path.name)
        destination = Gtk.DropDown.new_from_strings(names)
        dialog.set_extra_child(destination)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("copy", "Copy")
        dialog.set_response_appearance("copy", Adw.ResponseAppearance.SUGGESTED)
        def response(_dialog, action):
            if action != "copy":
                return
            name = names[destination.get_selected()]
            try:
                target = copy_image(image_path, self.cfg.collections[name].path)
            except (ValueError, OSError) as e:
                self._toast(f"Copy failed: {e}")
                return
            self._refresh_collections()
            self._toast(f"Copied {target.name} to {name}")
        dialog.connect("response", response)
        dialog.present()

    def _on_image_clicked(self, _btn: Gtk.Button | None, img_path: Path) -> bool:
        coll = self.cfg.active()
        try:
            compose_and_apply(self.cfg, self.state, img_path)
        except Exception as e:
            self._toast(f"apply failed: {e}")
            return False
        self.state.push_recent(coll.name, img_path.name)
        self.state.last_rotation = dt.datetime.now().isoformat(timespec="seconds")
        self.state.save()
        self._toast(f"Applied {img_path.name}")
        return True

    def _on_delete_clicked(self, _btn: Gtk.Button, img_path: Path) -> None:
        dialog = Adw.MessageDialog.new(self, "Move wallpaper to Trash?", None)
        dialog.set_body(f"“{img_path.name}” will be moved to Trash.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_response, img_path)
        dialog.present()

    def _on_delete_response(
        self, _dialog: Adw.MessageDialog, response: str, img_path: Path
    ) -> None:
        if response != "delete":
            return
        try:
            Gio.File.new_for_path(str(img_path)).trash(None)
        except (OSError, GLib.Error) as e:
            self._toast(f"Delete failed: {e}")
            return
        recent = self.state.recent.get(self.cfg.active_collection, [])
        if img_path.name in recent:
            recent.remove(img_path.name)
        self.state.save()
        self._refresh_browse()
        self._refresh_collections()
        self._toast(f"Deleted {img_path.name}")

    # ---------- import from local path ----------

    def _image_filter(self) -> Gtk.FileFilter:
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        for ext in IMAGE_EXTS:
            filt.add_pattern(f"*{ext}")
            filt.add_pattern(f"*{ext.upper()}")
        return filt

    def _on_add_images_clicked(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Add images to collection")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(self._image_filter())
        dialog.set_filters(filters)
        dialog.set_default_filter(self._image_filter())
        dialog.open_multiple(self, None, self._on_files_chosen)

    def _on_files_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        paths: list[Path] = []
        for i in range(files.get_n_items()):
            gfile = files.get_item(i)
            p = gfile.get_path()
            if p:
                paths.append(Path(p))
        self._import_paths(paths)

    def _on_import_folder_clicked(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Import all images from folder")
        dialog.select_folder(self, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        folder = Path(gfile.get_path())
        paths = [p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        self._import_paths(paths)

    def _import_paths(self, paths: list[Path]) -> None:
        if not paths:
            self._toast("No images selected")
            return
        coll = self.cfg.active()
        coll.path.mkdir(parents=True, exist_ok=True)
        added = skipped = 0
        for src in paths:
            if src.suffix.lower() not in IMAGE_EXTS:
                continue
            dst = coll.path / src.name
            if dst.exists():
                skipped += 1
                continue
            try:
                shutil.copy2(src, dst)
                added += 1
            except OSError:
                continue
        self._refresh_browse()
        self._refresh_collections()
        msg = f"Added {added} to {coll.name}"
        if skipped:
            msg += f" ({skipped} skipped)"
        self._toast(msg)

    # ---------- DuckDuckGo search tab ----------

    def _build_ddg_tab(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.ddg_query = Gtk.Entry()
        self.ddg_query.set_placeholder_text("Search the web for images…")
        self.ddg_query.set_hexpand(True)
        self.ddg_query.connect("activate", self._on_ddg_search_clicked)
        bar.append(self.ddg_query)

        bar.append(Gtk.Label(label="Engine:"))
        self.ddg_backend = Gtk.DropDown.new_from_strings(["DDG", "Bing", "Wallhaven", "Wikimedia Commons"])
        self.ddg_backend.set_selected(0)
        self.ddg_backend.connect("notify::selected", self._on_backend_changed)
        bar.append(self.ddg_backend)

        bar.append(Gtk.Label(label="Size:"))
        size_labels = [s or "Any" for s in DDG_SIZES]
        self.ddg_size = Gtk.DropDown.new_from_strings(size_labels)
        self.ddg_size.set_selected(0)  # Wallpaper
        bar.append(self.ddg_size)

        search_btn = Gtk.Button(label="Search")
        search_btn.add_css_class("suggested-action")
        search_btn.connect("clicked", self._on_ddg_search_clicked)
        bar.append(search_btn)
        cancel_btn = Gtk.Button.new_from_icon_name("process-stop-symbolic")
        cancel_btn.set_tooltip_text("Cancel search")
        cancel_btn.connect("clicked", self._cancel_search)
        bar.append(cancel_btn)

        outer.append(bar)

        self.ddg_flow = Gtk.FlowBox()
        self.ddg_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.ddg_flow.set_max_children_per_line(5)
        self.ddg_flow.set_column_spacing(10)
        self.ddg_flow.set_row_spacing(10)

        self.ddg_scroll = Gtk.ScrolledWindow()
        self.ddg_scroll.set_vexpand(True)
        self.ddg_scroll.set_child(self.ddg_flow)
        self.ddg_scroll.get_vadjustment().connect("value-changed", self._on_ddg_scroll)
        outer.append(self.ddg_scroll)

        self._ddg_generation = 0
        self._ddg_downloading = False
        self._ddg_items: list[tuple[Gtk.CheckButton, object]] = []
        self._ddg_vqd: str | None = None
        self._ddg_start = 0
        self._ddg_loading = False
        self._ddg_has_more = False
        self._ddg_query_text = ""
        self._ddg_size_value = ""
        self._ddg_backend = "ddg"

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, active in (("Select all", True), ("Clear selection", False)):
            button = Gtk.Button(label=label)
            button.connect("clicked", self._select_search_results, active)
            controls.append(button)
        self.ddg_more = Gtk.Button(label="Load more")
        self.ddg_more.set_sensitive(False)
        self.ddg_more.connect("clicked", self._retry_or_load_more)
        controls.append(self.ddg_more)
        outer.append(controls)
        download_btn = Gtk.Button(label="Download selected")
        self.ddg_download = download_btn
        download_btn.set_sensitive(False)
        download_btn.add_css_class("suggested-action")
        download_btn.connect("clicked", self._on_ddg_download_clicked)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.append(download_btn)
        footer.append(Gtk.Label(label="Save to:"))
        self.ddg_dest = Gtk.DropDown.new_from_strings([])
        footer.append(self.ddg_dest)
        self.ddg_spinner = Gtk.Spinner()
        footer.append(self.ddg_spinner)
        self.ddg_status = Gtk.Label(label="", xalign=0)
        self.ddg_status.set_hexpand(True)
        self.ddg_status.set_ellipsize(3)
        footer.append(self.ddg_status)
        outer.append(footer)
        return outer

    def _update_ddg_dropdown(self) -> None:
        if not hasattr(self, "ddg_dest"):
            return
        previous = self.ddg_dest.get_selected_item()
        destination = previous.get_string() if previous else self.cfg.active_collection
        names = list(self.cfg.collections.keys())
        model = Gtk.StringList.new(names)
        self.ddg_dest.set_model(model)
        if destination not in names:
            destination = self.cfg.active_collection
        if destination in names:
            self.ddg_dest.set_selected(names.index(destination))

    def _on_backend_changed(self, _dd, _pspec) -> None:
        backend = ("ddg", "bing", "wallhaven", "commons")[self.ddg_backend.get_selected()]
        sizes = BING_SIZES if backend == "bing" else DDG_SIZES if backend == "ddg" else API_SIZES
        labels = [s.capitalize() if s else "Any" for s in sizes]
        self.ddg_size.set_model(Gtk.StringList.new(labels))
        self.ddg_size.set_selected(0)

    def _on_ddg_search_clicked(self, _w) -> None:
        query = self.ddg_query.get_text().strip()
        if not query:
            self._toast("Enter a search query")
            return
        child = self.ddg_flow.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.ddg_flow.remove(child)
            child = nxt
        self._ddg_generation += 1
        self._ddg_items = []
        self._selection_changed()
        self._ddg_vqd = None
        self._ddg_start = 0
        self._ddg_loading = False
        self._ddg_has_more = True
        self._ddg_query_text = query
        self._ddg_backend = ("ddg", "bing", "wallhaven", "commons")[self.ddg_backend.get_selected()]
        sizes = BING_SIZES if self._ddg_backend == "bing" else DDG_SIZES if self._ddg_backend == "ddg" else API_SIZES
        idx = self.ddg_size.get_selected()
        self._ddg_size_value = sizes[idx] if 0 <= idx < len(sizes) else ""
        self.ddg_status.set_label("")
        self._ddg_load_next()

    def _on_ddg_scroll(self, adj: Gtk.Adjustment) -> None:
        if self._ddg_loading or not self._ddg_has_more or not self._ddg_query_text:
            return
        if adj.get_upper() <= adj.get_page_size():
            return
        if adj.get_value() + adj.get_page_size() >= adj.get_upper() - 400:
            self._ddg_load_next()

    def _ddg_load_next(self) -> None:
        if self._ddg_loading or not self._ddg_has_more:
            return
        self._ddg_loading = True
        self.ddg_more.set_sensitive(False)
        self.ddg_spinner.start()
        self.ddg_status.set_label(f"searching… ({len(self._ddg_items)} so far)")
        query = self._ddg_query_text
        size = self._ddg_size_value
        start = self._ddg_start
        vqd = self._ddg_vqd
        backend = self._ddg_backend
        generation = self._ddg_generation

        def worker() -> None:
            try:
                if backend == "bing":
                    results, has_more = bing_search(query, size=size, start=start)
                    GLib.idle_add(self._search_callback, generation, self._ddg_append, results, vqd, has_more)
                elif backend in ("wallhaven", "commons"):
                    results, token, has_more = catalog_search(backend, query, size=size, token=vqd)
                    GLib.idle_add(self._search_callback, generation, self._ddg_append, results, token, has_more)
                else:
                    results, new_vqd, has_more = ddg_search(
                        query, size=size, start=start, vqd=vqd
                    )
                    GLib.idle_add(self._search_callback, generation, self._ddg_append, results, new_vqd, has_more)
            except Exception as e:
                GLib.idle_add(self._search_callback, generation, self._ddg_error, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_search(self, _button) -> None:
        self._ddg_generation += 1
        self._ddg_loading = False
        self._ddg_has_more = False
        self.ddg_spinner.stop()
        self.ddg_more.set_sensitive(False)
        self.ddg_status.set_label("Search cancelled")

    def _retry_or_load_more(self, _button) -> None:
        self._ddg_has_more = True
        self._ddg_load_next()

    def _search_callback(self, generation, callback, *args) -> bool:
        if generation == self._ddg_generation:
            callback(*args)
        return False

    def _selection_changed(self, *_args) -> None:
        count = sum(check.get_active() for check, _item in self._ddg_items)
        self.ddg_download.set_label(f"Download selected ({count})" if count else "Download selected")
        self.ddg_download.set_sensitive(count > 0 and not self._ddg_downloading)

    def _select_search_results(self, _button, active) -> None:
        for check, _item in self._ddg_items:
            check.set_active(active)

    def _ddg_error(self, msg: str) -> bool:
        self.ddg_spinner.stop()
        self._ddg_loading = False
        self._ddg_has_more = False
        self.ddg_more.set_sensitive(True)
        self.ddg_more.set_label("Retry")
        self.ddg_status.set_label(f"error: {msg}")
        self._toast(f"Search failed: {msg}")
        return False

    def _ddg_append(self, results: list, vqd: str | None, has_more: bool) -> bool:
        self.ddg_spinner.stop()
        self._ddg_loading = False
        self._ddg_vqd = vqd
        self._ddg_has_more = has_more

        seen = {it.image_url for _, it in self._ddg_items}
        added = 0
        for it in results:
            if it.image_url in seen:
                continue
            seen.add(it.image_url)

            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.set_size_request(THUMB_W, -1)

            pic = Gtk.Picture()
            pic.set_size_request(THUMB_W, THUMB_H)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            card.append(pic)
            self._start_url_thumb_load(it.thumb_url or it.image_url, pic)

            title_text = it.title or it.source or "image"
            if len(title_text) > 40:
                title_text = title_text[:37] + "…"
            lbl = Gtk.Label(label=title_text)
            lbl.add_css_class("caption")
            lbl.set_ellipsize(3)
            lbl.set_wrap(False)
            lbl.set_max_width_chars(30)
            card.append(lbl)

            dims = f"{it.width}×{it.height}" if it.width and it.height else ""
            if dims:
                dim_lbl = Gtk.Label(label=dims)
                dim_lbl.add_css_class("caption")
                dim_lbl.add_css_class("dim-label")
                card.append(dim_lbl)

            if it.page_url:
                source_link = Gtk.LinkButton.new_with_label(it.page_url, "Open source")
                card.append(source_link)
            check = Gtk.CheckButton(label="Select")
            check.set_active(False)
            check.connect("toggled", self._selection_changed)
            card.append(check)

            self.ddg_flow.append(card)
            self._ddg_items.append((check, it))
            added += 1

        if results and added == 0:
            self._ddg_has_more = False
        self.ddg_more.set_label("Load more")
        self.ddg_more.set_sensitive(self._ddg_has_more)
        self._ddg_start += len(results) if results else 0
        total = len(self._ddg_items)
        if added == 0 and not has_more:
            self._ddg_has_more = False
            self.ddg_status.set_label(f"end of results ({total} shown)")
        else:
            self.ddg_status.set_label(f"{total} results")
        return False

    def _start_url_thumb_load(self, url: str, picture: Gtk.Picture) -> None:
        if not url:
            return

        def worker() -> None:
            try:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                        ),
                        "Referer": "https://duckduckgo.com/",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
                loader = GdkPixbuf.PixbufLoader()
                loader.write(data)
                loader.close()
                pix = loader.get_pixbuf()
                if pix is None:
                    return
                GLib.idle_add(picture.set_pixbuf, pix)
            except Exception:
                return

        threading.Thread(target=worker, daemon=True).start()

    def _on_ddg_download_clicked(self, _btn: Gtk.Button) -> None:
        names = list(self.cfg.collections.keys())
        idx = self.ddg_dest.get_selected()
        if not names or idx >= len(names):
            self._toast("No destination collection")
            return
        dest_name = names[idx]
        dest = self.cfg.collections[dest_name].path
        chosen = [it for check, it in self._ddg_items if check.get_active()]
        if not chosen:
            self._toast("Nothing selected")
            return
        self.ddg_spinner.start()
        self.ddg_status.set_label(f"downloading {len(chosen)}…")

        self._ddg_downloading = True
        self._selection_changed()

        def worker() -> None:
            from downloads import download_image
            added = skipped = failed = 0
            last_error = ""
            for item in chosen:
                try:
                    if download_image(item, dest) is None:
                        skipped += 1
                    else:
                        added += 1
                except Exception as e:
                    failed += 1
                    last_error = str(e)
            GLib.idle_add(self._ddg_download_done, added, skipped, failed, last_error, dest_name)

        threading.Thread(target=worker, daemon=True).start()

    def _ddg_download_done(self, added, skipped, failed, error, dest_name) -> bool:
        self.ddg_spinner.stop()
        self._ddg_downloading = False
        self._selection_changed()
        message = f"Added {added} to {dest_name}; {skipped} already saved; {failed} failed"
        self.ddg_status.set_label(message)
        self.ddg_status.set_tooltip_text(error or message)
        self._toast(message + (f": {error}" if failed else ""))
        self._refresh_collections()
        if dest_name == self.cfg.active_collection:
            self._refresh_browse()
        return False

    def _open_collection_folder(self, _button) -> None:
        try:
            folder = self.cfg.active().path
            folder.mkdir(parents=True, exist_ok=True)
            Gtk.UriLauncher.new(folder.as_uri()).launch(self, None, self._folder_opened)
        except (OSError, GLib.Error) as e:
            self._toast(str(e))

    def _folder_opened(self, launcher, result) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as e:
            self._toast(f"Could not open folder: {e}")

    def _navigate_wallpaper(self, forward: bool) -> None:
        coll = self.cfg.active()
        images = list_images(coll.path)
        recent = self.state.recent.get(coll.name, [])
        if forward:
            chosen = pick_random(images, recent)
        else:
            existing = {path.name: path for path in images}
            chosen = next((existing[name] for name in recent[1:] if name in existing), None)
        if chosen is None:
            self._toast("No next wallpaper" if forward else "No previous wallpaper")
            return
        previous_history = list(recent)
        if not forward:
            self.state.recent[coll.name] = recent[recent.index(chosen.name):]
        if not self._on_image_clicked(None, chosen) and not forward:
            self.state.recent[coll.name] = previous_history

    def _on_key_pressed(self, _controller, keyval, _keycode, modifiers) -> bool:
        if modifiers & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_f, Gdk.KEY_F):
                self.view_stack.set_visible_child_name("ddg")
                self.ddg_query.grab_focus()
                return True
            if keyval in (Gdk.KEY_r, Gdk.KEY_R):
                self._refresh_collections()
                self._refresh_browse()
                return True
        if modifiers & Gdk.ModifierType.ALT_MASK and keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            self._navigate_wallpaper(keyval == Gdk.KEY_Right)
            return True
        return False

    # ---------- settings ----------

    def _build_settings_tab(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for setter in (box.set_margin_top, box.set_margin_bottom, box.set_margin_start, box.set_margin_end):
            setter(24)
        scroll.set_child(box)
        self.settings_fields = {}

        def row(label, key, widget):
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            title = Gtk.Label(label=label, xalign=0)
            title.set_hexpand(True)
            line.append(title)
            line.append(widget)
            self.settings_fields[key] = widget
            box.append(line)

        def choices(label, key, labels, values, current):
            widget = Gtk.DropDown.new_from_strings(labels)
            widget.set_selected(values.index(current) if current in values else 0)
            widget.setting_values = values
            row(label, key, widget)

        def toggle(label, key, value):
            widget = Gtk.Switch(active=value, valign=Gtk.Align.CENTER)
            row(label, key, widget)

        def number(label, key, value, low, high):
            widget = Gtk.SpinButton.new_with_range(low, high, 1)
            widget.set_value(value)
            row(label, key, widget)

        def entry(label, key, value):
            row(label, key, Gtk.Entry(text=value))

        choices("Fill style", "fill_style", ["Blurred background", "Fit (black bars)", "Fill (crop)", "Stretch", "Center"],
                ["blur", "fit", "fill", "stretch", "center"], self.cfg.fill_style)
        number("Background blur", "blur", self.cfg.blur, 0, 200)
        toggle("Show clock", "clock_enabled", self.cfg.clock_enabled)
        choices("Clock position", "clock_side", ["Left", "Right"], ["left", "right"], self.cfg.clock_side)
        choices("Time style", "time_preset", ["12-hour", "24-hour", "Custom"],
                ["%-I:%M %p", "%H:%M", "custom"], self.cfg.time_format if self.cfg.time_format in ("%-I:%M %p", "%H:%M") else "custom")
        entry("Custom time format", "time_format", self.cfg.time_format)
        entry("Date format", "date_format", self.cfg.date_format)
        number("Time font size", "time_size", self.cfg.time_size, 12, 400)
        number("Date font size", "date_size", self.cfg.date_size, 12, 300)
        choices("When to change wallpaper", "update_mode", ["At intervals", "Daily at a set time", "Manual only"],
                ["interval", "daily", "manual"], self.cfg.update_mode)
        number("Update interval (minutes)", "interval_minutes", self.cfg.interval_minutes, 1, 10080)
        entry("Daily update time (HH:MM)", "daily_time", self.cfg.daily_time)
        toggle("Start wallpaper updates at login", "autostart", self.cfg.autostart)
        toggle("Change wallpaper at login", "update_on_start", self.cfg.update_on_start)
        hint = Gtk.Label(label="Daily time uses your local timezone. The clock refreshes every minute.\nDeleting a collection keeps its image files.", xalign=0)
        hint.set_wrap(True)
        hint.add_css_class("dim-label")
        box.append(hint)
        save = Gtk.Button(label="Save settings")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save_settings)
        box.append(save)
        for key in ("update_mode", "time_preset"):
            self.settings_fields[key].connect("notify::selected", self._settings_sensitivity)
        for key in ("clock_enabled", "autostart"):
            self.settings_fields[key].connect("notify::active", self._settings_sensitivity)
        self._settings_sensitivity()
        return scroll

    def _settings_sensitivity(self, *_args) -> None:
        fields = self.settings_fields
        mode = fields["update_mode"].setting_values[fields["update_mode"].get_selected()]
        fields["interval_minutes"].set_sensitive(mode == "interval")
        fields["daily_time"].set_sensitive(mode == "daily")
        clock = fields["clock_enabled"].get_active()
        for key in ("clock_side", "time_preset", "date_format", "time_size", "date_size"):
            fields[key].set_sensitive(clock)
        fields["time_format"].set_sensitive(clock and fields["time_preset"].get_selected() == 2)
        fields["update_on_start"].set_sensitive(fields["autostart"].get_active())

    def _save_settings(self, _button) -> None:
        import datetime as dt
        from dataclasses import replace
        from scheduler import sync_schedule
        values = {}
        for key, widget in self.settings_fields.items():
            if isinstance(widget, Gtk.DropDown):
                values[key] = widget.setting_values[widget.get_selected()]
            elif isinstance(widget, Gtk.Switch):
                values[key] = widget.get_active()
            elif isinstance(widget, Gtk.SpinButton):
                values[key] = widget.get_value_as_int()
            else:
                values[key] = widget.get_text().strip()
        preset = values.pop("time_preset")
        if preset != "custom":
            values["time_format"] = preset
        try:
            parsed_time = dt.datetime.strptime(values["daily_time"], "%H:%M")
            values["daily_time"] = parsed_time.strftime("%H:%M")
            for key in ("time_format", "date_format"):
                if not values[key]:
                    raise ValueError("Time and date formats cannot be empty")
                dt.datetime.now().strftime(values[key])
            cfg = replace(self.cfg, **values)
            cfg.save()
        except (ValueError, OSError) as e:
            self._toast(f"Settings not saved: {e}")
            return
        self.cfg = cfg
        _button.set_sensitive(False)
        self._toast("Settings saved; updating schedule…")

        def worker():
            try:
                sync_schedule(cfg)
                GLib.idle_add(self._toast, "Settings and wallpaper schedule updated")
            except Exception as e:
                GLib.idle_add(self._toast, f"Settings saved; schedule failed: {e}")
            finally:
                GLib.idle_add(_button.set_sensitive, True)
        threading.Thread(target=worker, daemon=True).start()
        current = self.state.current_for(self.cfg.active_collection)
        if current:
            path = self.cfg.active().path / current
            if path.is_file():
                try:
                    compose_and_apply(self.cfg, self.state, path)
                    self.state.save()
                except Exception as e:
                    self._toast(f"Settings saved; preview failed: {e}")

    # ---------- helpers ----------

    def _toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(message))


class LingoApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.lingo.Lingo")

    def do_activate(self) -> None:
        win = LingoWindow(self)
        win.present()


def run() -> None:
    app = LingoApp()
    app.run(None)
