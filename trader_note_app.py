# -*- coding: utf-8 -*-
"""
Stock Chart Note App (PyQt5) - OneNote-style Step/Page Navigator

Version: 0.1.0  (2025-12-20)
Versioning: MAJOR.MINOR.PATCH (SemVer)

This version (v0.1.0) - Release Notes:
- Left panel: Step selection (OneNote-like navigation)
- Right panel: Page viewer/editor
  - Page is split into two sections:
    - Left: Large chart image viewer (supports drag & drop + file select)
    - Right: Multi-line text editor for description
- Bottom navigator:
  - Shows current/total pages (e.g., "3 / 12")
  - Prev/Next arrows for page navigation
  - Add page (+) and Delete page
- JSON-based persistence (no DB yet)
  - Saves: steps, pages, image paths (stored under ./assets), and page text

How to run:
- Ensure PyQt5 installed:
  pip install PyQt5
- Run:
  python trader_note_app_v0_1.py
"""

import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)


APP_TITLE = "Trader Chart Note (v0.1.0)"
DEFAULT_DB_PATH = os.path.join("data", "notes_db.json")
ASSETS_DIR = "assets"


def _now_epoch() -> int:
    return int(time.time())


def _uuid() -> str:
    return str(uuid.uuid4())


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _safe_write_json(path: str, data: Dict[str, Any]) -> None:
    _ensure_dir(os.path.dirname(path) or ".")
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _relpath_norm(path: str) -> str:
    # store relative paths with forward slashes for portability
    return path.replace("\\", "/")


def _abspath_from_rel(rel_path: str) -> str:
    return os.path.abspath(rel_path.replace("/", os.sep))


@dataclass
class Page:
    id: str
    image_path: str  # relative path under project
    note_text: str
    created_at: int
    updated_at: int


@dataclass
class Step:
    id: str
    name: str
    pages: List[Page]
    last_page_index: int = 0


class NoteDB:
    """JSON persistence layer for steps/pages."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.data: Dict[str, Any] = {}
        self.steps: List[Step] = []
        self.ui_state: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                # fallback to fresh DB
                self.data = {}
        if not self.data:
            self.data = self._default_data()

        self.ui_state = self.data.get("ui_state", {})
        self.steps = self._parse_steps(self.data.get("steps", []))

        # Ensure at least one step/page exists
        if not self.steps:
            self.steps = self._parse_steps(self._default_data()["steps"])
        for st in self.steps:
            if not st.pages:
                st.pages.append(self.new_page())

    def save(self) -> None:
        self.data["version"] = "0.1.0"
        self.data["updated_at"] = _now_epoch()
        self.data["steps"] = self._serialize_steps(self.steps)
        self.data["ui_state"] = self.ui_state
        _safe_write_json(self.db_path, self.data)

    @staticmethod
    def _default_data() -> Dict[str, Any]:
        # You can rename these in-app later (Rename Step)
        step_names = ["Step 1", "Step 2", "Step 3"]
        steps = []
        for name in step_names:
            steps.append(
                {
                    "id": _uuid(),
                    "name": name,
                    "last_page_index": 0,
                    "pages": [
                        {
                            "id": _uuid(),
                            "image_path": "",
                            "note_text": "",
                            "created_at": _now_epoch(),
                            "updated_at": _now_epoch(),
                        }
                    ],
                }
            )
        return {
            "version": "0.1.0",
            "created_at": _now_epoch(),
            "updated_at": _now_epoch(),
            "steps": steps,
            "ui_state": {},
        }

    @staticmethod
    def _parse_steps(steps_raw: List[Dict[str, Any]]) -> List[Step]:
        steps: List[Step] = []
        for s in steps_raw:
            pages_raw = s.get("pages", [])
            pages: List[Page] = []
            for p in pages_raw:
                pages.append(
                    Page(
                        id=str(p.get("id", _uuid())),
                        image_path=str(p.get("image_path", "")),
                        note_text=str(p.get("note_text", "")),
                        created_at=int(p.get("created_at", _now_epoch())),
                        updated_at=int(p.get("updated_at", _now_epoch())),
                    )
                )
            steps.append(
                Step(
                    id=str(s.get("id", _uuid())),
                    name=str(s.get("name", "Untitled Step")),
                    pages=pages,
                    last_page_index=int(s.get("last_page_index", 0)),
                )
            )
        return steps

    @staticmethod
    def _serialize_steps(steps: List[Step]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for st in steps:
            out.append(
                {
                    "id": st.id,
                    "name": st.name,
                    "last_page_index": st.last_page_index,
                    "pages": [
                        {
                            "id": pg.id,
                            "image_path": pg.image_path,
                            "note_text": pg.note_text,
                            "created_at": pg.created_at,
                            "updated_at": pg.updated_at,
                        }
                        for pg in st.pages
                    ],
                }
            )
        return out

    @staticmethod
    def new_page() -> Page:
        now = _now_epoch()
        return Page(id=_uuid(), image_path="", note_text="", created_at=now, updated_at=now)

    def get_step_by_id(self, step_id: str) -> Optional[Step]:
        for st in self.steps:
            if st.id == step_id:
                return st
        return None

    def add_step(self, name: str) -> Step:
        st = Step(id=_uuid(), name=name, pages=[self.new_page()], last_page_index=0)
        self.steps.append(st)
        return st

    def delete_step(self, step_id: str) -> bool:
        if len(self.steps) <= 1:
            return False
        self.steps = [s for s in self.steps if s.id != step_id]
        return True


class ImageViewer(QWidget):
    imageDropped = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

        self._pixmap: Optional[QPixmap] = None
        self._scaled_pixmap: Optional[QPixmap] = None

        self._label = QLabel("Drop an image here\nor click 'Set Image...'", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMinimumSize(200, 200)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)

    def clear(self) -> None:
        self._pixmap = None
        self._scaled_pixmap = None
        self._label.setText("Drop an image here\nor click 'Set Image...'")
        self._label.setPixmap(QPixmap())

    def set_image(self, image_abs_path: str) -> None:
        pm = QPixmap(image_abs_path)
        if pm.isNull():
            self.clear()
            return
        self._pixmap = pm
        self._update_scaled()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self) -> None:
        if not self._pixmap or self._pixmap.isNull():
            return
        # Fit to viewport width while preserving aspect ratio
        vp = self._scroll.viewport().size()
        target_w = max(1, vp.width() - 10)
        scaled = self._pixmap.scaledToWidth(target_w, Qt.SmoothTransformation)
        self._scaled_pixmap = scaled
        self._label.setPixmap(self._scaled_pixmap)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setText("")  # clear placeholder

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = urls[0].toLocalFile()
        if local_path and os.path.isfile(local_path):
            self.imageDropped.emit(local_path)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)

        self.db = NoteDB(DEFAULT_DB_PATH)

        # State
        self.current_step_id: Optional[str] = None
        self.current_page_index: int = 0
        self._loading_ui: bool = False

        # Auto-save debounce for text
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_text_to_model_and_save)

        self._build_ui()
        self._load_ui_state_or_defaults()
        self._refresh_steps_list(select_current=True)
        self._load_current_page_to_ui()

        # Shortcuts
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_prev_page)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.go_next_page)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_page)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.force_save)

    def closeEvent(self, event) -> None:
        try:
            self._flush_text_to_model_and_save()
            self.db.save()
        except Exception:
            pass
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)

        main_splitter = QSplitter(Qt.Horizontal, root)

        # Left panel: steps list + controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        left_controls = QHBoxLayout()
        self.btn_add_step = QToolButton()
        self.btn_add_step.setText("+ Step")
        self.btn_rename_step = QToolButton()
        self.btn_rename_step.setText("Rename")
        self.btn_del_step = QToolButton()
        self.btn_del_step.setText("Del")

        self.btn_add_step.clicked.connect(self.add_step)
        self.btn_rename_step.clicked.connect(self.rename_step)
        self.btn_del_step.clicked.connect(self.delete_step)

        left_controls.addWidget(self.btn_add_step)
        left_controls.addWidget(self.btn_rename_step)
        left_controls.addWidget(self.btn_del_step)
        left_controls.addStretch(1)

        self.steps_list = QListWidget()
        self.steps_list.currentRowChanged.connect(self._on_step_selected)

        left_layout.addLayout(left_controls)
        left_layout.addWidget(self.steps_list, 1)

        # Right panel: page content + navigator
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.page_splitter = QSplitter(Qt.Horizontal)

        # Image section
        img_container = QWidget()
        img_layout = QVBoxLayout(img_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(6)

        img_toolbar = QHBoxLayout()
        self.btn_set_image = QPushButton("Set Image...")
        self.btn_clear_image = QPushButton("Clear Image")
        self.btn_set_image.clicked.connect(self.set_image_via_dialog)
        self.btn_clear_image.clicked.connect(self.clear_image)

        img_toolbar.addWidget(self.btn_set_image)
        img_toolbar.addWidget(self.btn_clear_image)
        img_toolbar.addStretch(1)

        self.image_viewer = ImageViewer()
        self.image_viewer.imageDropped.connect(self._on_image_dropped)

        img_layout.addLayout(img_toolbar)
        img_layout.addWidget(self.image_viewer, 1)

        # Text section
        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        text_header = QHBoxLayout()
        self.text_title = QLabel("Description")
        self.text_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.btn_clear_text = QPushButton("Clear Text")
        self.btn_clear_text.clicked.connect(self.clear_text)

        text_header.addWidget(self.text_title)
        text_header.addStretch(1)
        text_header.addWidget(self.btn_clear_text)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Write your analysis / explanation here...")
        self.text_edit.textChanged.connect(self._on_text_changed)

        text_layout.addLayout(text_header)
        text_layout.addWidget(self.text_edit, 1)

        self.page_splitter.addWidget(img_container)
        self.page_splitter.addWidget(text_container)
        self.page_splitter.setStretchFactor(0, 1)
        self.page_splitter.setStretchFactor(1, 1)

        # Navigator bar
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)

        self.btn_prev = QToolButton()
        self.btn_prev.setText("◀")
        self.btn_prev.clicked.connect(self.go_prev_page)

        self.lbl_page = QLabel("0 / 0")
        self.lbl_page.setAlignment(Qt.AlignCenter)
        self.lbl_page.setMinimumWidth(80)

        self.btn_next = QToolButton()
        self.btn_next.setText("▶")
        self.btn_next.clicked.connect(self.go_next_page)

        self.btn_add_page = QToolButton()
        self.btn_add_page.setText("+ Page")
        self.btn_add_page.clicked.connect(self.add_page)

        self.btn_del_page = QToolButton()
        self.btn_del_page.setText("Del Page")
        self.btn_del_page.clicked.connect(self.delete_page)

        nav.addWidget(self.btn_prev)
        nav.addWidget(self.lbl_page)
        nav.addWidget(self.btn_next)
        nav.addStretch(1)
        nav.addWidget(self.btn_add_page)
        nav.addWidget(self.btn_del_page)

        right_layout.addWidget(self.page_splitter, 1)
        right_layout.addLayout(nav)

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([260, 940])

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

    def _load_ui_state_or_defaults(self) -> None:
        # Pick last selected step if exists
        step_id = self.db.ui_state.get("selected_step_id")
        page_idx = self.db.ui_state.get("current_page_index", 0)

        if step_id and self.db.get_step_by_id(step_id):
            self.current_step_id = step_id
        else:
            self.current_step_id = self.db.steps[0].id if self.db.steps else None

        self.current_page_index = int(page_idx) if isinstance(page_idx, int) else 0

        # Clamp to step pages
        st = self.current_step()
        if st:
            if st.pages:
                self.current_page_index = max(0, min(self.current_page_index, len(st.pages) - 1))
            else:
                self.current_page_index = 0

    def current_step(self) -> Optional[Step]:
        if not self.current_step_id:
            return None
        return self.db.get_step_by_id(self.current_step_id)

    def current_page(self) -> Optional[Page]:
        st = self.current_step()
        if not st or not st.pages:
            return None
        idx = max(0, min(self.current_page_index, len(st.pages) - 1))
        return st.pages[idx]

    def _refresh_steps_list(self, select_current: bool = False) -> None:
        self.steps_list.blockSignals(True)
        self.steps_list.clear()

        current_row = 0
        for i, st in enumerate(self.db.steps):
            item = QListWidgetItem(st.name)
            item.setData(Qt.UserRole, st.id)
            self.steps_list.addItem(item)
            if select_current and st.id == self.current_step_id:
                current_row = i

        self.steps_list.setCurrentRow(current_row)
        self.steps_list.blockSignals(False)

    def _on_step_selected(self, row: int) -> None:
        if row < 0:
            return
        item = self.steps_list.item(row)
        if not item:
            return

        # Save current edits first
        self._flush_text_to_model_and_save()

        step_id = item.data(Qt.UserRole)
        if not step_id:
            return

        self.current_step_id = str(step_id)
        st = self.current_step()
        if not st:
            return

        # restore last_page_index per step (OneNote-like)
        self.current_page_index = max(0, min(st.last_page_index, len(st.pages) - 1))
        self._save_ui_state()
        self._load_current_page_to_ui()

    def _save_ui_state(self) -> None:
        self.db.ui_state["selected_step_id"] = self.current_step_id
        self.db.ui_state["current_page_index"] = self.current_page_index

    def _load_current_page_to_ui(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            self.image_viewer.clear()
            self.text_edit.clear()
            self._update_nav()
            return

        self._loading_ui = True
        try:
            # Image
            if pg.image_path:
                abs_path = _abspath_from_rel(pg.image_path)
                if os.path.exists(abs_path):
                    self.image_viewer.set_image(abs_path)
                else:
                    self.image_viewer.clear()
            else:
                self.image_viewer.clear()

            # Text
            self.text_edit.setPlainText(pg.note_text or "")

            # Update nav
            self._update_nav()

        finally:
            self._loading_ui = False

    def _update_nav(self) -> None:
        st = self.current_step()
        total = len(st.pages) if st else 0
        cur = (self.current_page_index + 1) if total > 0 else 0
        self.lbl_page.setText(f"{cur} / {total}")

        self.btn_prev.setEnabled(total > 0 and self.current_page_index > 0)
        self.btn_next.setEnabled(total > 0 and self.current_page_index < total - 1)
        self.btn_del_page.setEnabled(total > 1)

    def _on_text_changed(self) -> None:
        if self._loading_ui:
            return
        # Debounced autosave
        self._save_timer.start(450)

    def _flush_text_to_model_and_save(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            return
        if self._loading_ui:
            return

        new_text = self.text_edit.toPlainText()
        if pg.note_text != new_text:
            pg.note_text = new_text
            pg.updated_at = _now_epoch()

        # Track last visited page for this step
        st.last_page_index = self.current_page_index

        self._save_ui_state()
        self.db.save()

    def force_save(self) -> None:
        self._flush_text_to_model_and_save()
        QMessageBox.information(self, "Saved", "Saved to JSON.")

    # ---------- Page navigation ----------
    def go_prev_page(self) -> None:
        st = self.current_step()
        if not st or self.current_page_index <= 0:
            return
        self._flush_text_to_model_and_save()
        self.current_page_index -= 1
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self._load_current_page_to_ui()

    def go_next_page(self) -> None:
        st = self.current_step()
        if not st or self.current_page_index >= len(st.pages) - 1:
            return
        self._flush_text_to_model_and_save()
        self.current_page_index += 1
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self._load_current_page_to_ui()

    def add_page(self) -> None:
        st = self.current_step()
        if not st:
            return
        self._flush_text_to_model_and_save()

        # Policy: add after current page
        insert_at = self.current_page_index + 1
        st.pages.insert(insert_at, self.db.new_page())
        self.current_page_index = insert_at
        st.last_page_index = self.current_page_index

        self._save_ui_state()
        self.db.save()
        self._load_current_page_to_ui()

    def delete_page(self) -> None:
        st = self.current_step()
        if not st or len(st.pages) <= 1:
            return

        reply = QMessageBox.question(
            self,
            "Delete Page",
            "Delete current page?\n(This cannot be undone in v0.1.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        pg = self.current_page()
        if pg and pg.image_path:
            # optional: keep asset; v0.1 does not delete files automatically
            pass

        self._flush_text_to_model_and_save()
        del st.pages[self.current_page_index]
        self.current_page_index = max(0, min(self.current_page_index, len(st.pages) - 1))
        st.last_page_index = self.current_page_index

        self._save_ui_state()
        self.db.save()
        self._load_current_page_to_ui()

    # ---------- Image handling ----------
    def _on_image_dropped(self, path: str) -> None:
        self._set_image_from_file(path)

    def set_image_via_dialog(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Chart Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*.*)",
        )
        if not file_path:
            return
        self._set_image_from_file(file_path)

    def clear_image(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            return
        self._flush_text_to_model_and_save()
        pg.image_path = ""
        pg.updated_at = _now_epoch()
        self.db.save()
        self.image_viewer.clear()

    def _set_image_from_file(self, src_path: str) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            return
        if not os.path.isfile(src_path):
            return

        self._flush_text_to_model_and_save()

        ext = os.path.splitext(src_path)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]:
            QMessageBox.warning(self, "Invalid file", "Please select an image file.")
            return

        # Copy into assets for portability
        safe_step = "".join(ch for ch in st.name if ch.isalnum() or ch in (" ", "_", "-")).strip().replace(" ", "_")
        safe_step = safe_step or st.id[:8]

        dst_dir = os.path.join(ASSETS_DIR, safe_step)
        _ensure_dir(dst_dir)

        dst_name = f"{pg.id}{ext}"
        dst_rel = _relpath_norm(os.path.join(dst_dir, dst_name))
        dst_abs = _abspath_from_rel(dst_rel)

        try:
            shutil.copy2(src_path, dst_abs)
        except Exception as e:
            QMessageBox.critical(self, "Copy failed", f"Failed to copy image:\n{e}")
            return

        pg.image_path = dst_rel
        pg.updated_at = _now_epoch()

        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self.db.save()

        self.image_viewer.set_image(dst_abs)

    # ---------- Text handling ----------
    def clear_text(self) -> None:
        self.text_edit.clear()

    # ---------- Step management (simple utilities) ----------
    def add_step(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Step", "Step name:")
        if not ok or not name.strip():
            return
        self._flush_text_to_model_and_save()
        st = self.db.add_step(name.strip())
        self.current_step_id = st.id
        self.current_page_index = 0
        self._save_ui_state()
        self.db.save()
        self._refresh_steps_list(select_current=True)
        self._load_current_page_to_ui()

    def rename_step(self) -> None:
        st = self.current_step()
        if not st:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Step", "New name:", text=st.name)
        if not ok or not new_name.strip():
            return
        st.name = new_name.strip()
        self.db.save()
        self._refresh_steps_list(select_current=True)

    def delete_step(self) -> None:
        st = self.current_step()
        if not st:
            return
        if len(self.db.steps) <= 1:
            QMessageBox.warning(self, "Not allowed", "At least one step must remain.")
            return

        reply = QMessageBox.question(
            self,
            "Delete Step",
            f"Delete step '{st.name}' and all its pages?\n(This cannot be undone in v0.1.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        step_id = st.id
        ok = self.db.delete_step(step_id)
        if not ok:
            QMessageBox.warning(self, "Failed", "Cannot delete the last remaining step.")
            return

        # Move selection to first step
        self.current_step_id = self.db.steps[0].id
        self.current_page_index = max(0, min(self.db.steps[0].last_page_index, len(self.db.steps[0].pages) - 1))
        self._save_ui_state()
        self.db.save()
        self._refresh_steps_list(select_current=True)
        self._load_current_page_to_ui()


def main() -> None:
    _ensure_dir("data")
    _ensure_dir(ASSETS_DIR)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
