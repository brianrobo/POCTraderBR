# -*- coding: utf-8 -*-
"""
Trader Chart Note App (PyQt5) - Folder(Category) + Item 구조

Version: 0.6.0  (2026-01-01)
Versioning: MAJOR.MINOR.PATCH (SemVer)

Release Notes (v0.6.0):
- (ARCH) 좌측 트리 구조를 "Folder(Category) / Item"으로 재구성
  - Category는 폴더(서브 폴더 가능)
  - Item만이 실제 데이터(Chart A/B, Annotation, Caption, Description/Checklist, Page)를 보유
  - "Add Folder"는 현재 선택된 Category 하위에 서브 폴더를 추가
    * Item이 선택되어 있으면 그 부모 Category 하위에 폴더 추가
  - "Add Item"은 현재 Category 하위에 Item 추가
- (UX) Drag & Drop 제거
  - Folder/Item 위치 변경은 "Move Up / Move Down" 버튼으로만 지원
  - 구조적으로 안정적인 재빌드/저장 방식 적용
- (UI) 중앙 레이아웃 원복/유지
  - Chart A/B는 Vertical(위/아래)
  - Description/Checklist + Global Ideas는 차트 오른쪽(수평 분리)
- (DEV) Debug output(Trace) 패널 유지 (v0.5.1 기능 유지)
  - Show/Hide, Clear/Copy, 라인수 상한, Splitter 상태 저장/복원

Dependencies:
  pip install PyQt5
"""

import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import (
    Qt,
    QTimer,
    pyqtSignal,
    QRectF,
    QPointF,
    QRect,
    QSize,
    QPoint,
    QEvent,
)
from PyQt5.QtGui import (
    QImage,
    QKeySequence,
    QPixmap,
    QPainterPath,
    QPen,
    QColor,
    QPainter,
    QIcon,
    QTextCharFormat,
    QTextListFormat,
    QFont,
    QBrush,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QShortcut,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QInputDialog,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QPushButton,
    QLayout,
    QWidgetItem,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
    QMenu,
    QPlainTextEdit,
    QAbstractItemView,
    QButtonGroup,
    QSizePolicy,
)

APP_TITLE = "Trader Chart Note (v0.6.0)"
DEFAULT_DB_PATH = os.path.join("data", "notes_db.json")
ASSETS_DIR = "assets"

DEFAULT_CHECK_QUESTIONS = [
    "Q. 매집구간이 보이는가?",
    "Q. 매물이 모두 정리가 되었는가? 그럴만한 상승구간과 거래량이 나왔는가?",
    "Q. 그렇지 않다면 지지선, 깨지말아야할 선은 무엇인가?",
    "Q. 돌아서는 구간을 찾을 수 있는가?",
]

COLOR_DEFAULT = "#222222"
COLOR_RED = "#FF3C3C"
COLOR_BLUE = "#2D6BFF"
COLOR_YELLOW = "#FFD400"

ROOT_CATEGORY_ID = "root"


def _now_epoch() -> int:
    return int(time.time())


def _uuid() -> str:
    return str(uuid.uuid4())


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _safe_write_json(path: str, data: Dict[str, Any], retries: int = 12, base_delay: float = 0.08) -> bool:
    """
    Atomic-ish JSON save for Windows.
    - Writes to .tmp then os.replace(tmp, path)
    - If destination is locked (PermissionError), retry with backoff
    - If still failing, writes autosave file and returns False (no crash)
    """
    _ensure_dir(os.path.dirname(path) or ".")
    tmp_path = f"{path}.tmp"

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        return False

    for i in range(max(1, retries)):
        try:
            os.replace(tmp_path, path)
            return True
        except PermissionError:
            time.sleep(base_delay * (1.6 ** i))
        except OSError:
            time.sleep(base_delay * (1.6 ** i))

    try:
        autosave_path = f"{path}.autosave.{_now_epoch()}.json"
        try:
            os.replace(tmp_path, autosave_path)
        except Exception:
            with open(autosave_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False


def _relpath_norm(path: str) -> str:
    return path.replace("\\", "/")


def _abspath_from_rel(rel_path: str) -> str:
    return os.path.abspath(rel_path.replace("/", os.sep))


def _sanitize_for_folder(name: str, fallback: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "_", "-")).strip().replace(" ", "_")
    return safe or fallback


def _make_copy_icon(size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    fg = QColor("#2E2E2E")
    pen = QPen(fg, 1.2)
    p.setPen(pen)

    back = QRect(4, 3, 9, 10)
    p.drawRoundedRect(back, 1.5, 1.5)

    front = QRect(2, 5, 9, 10)
    p.drawRoundedRect(front, 1.5, 1.5)

    p.drawLine(4, 9, 9, 9)
    p.drawLine(4, 11, 9, 11)

    p.end()
    return QIcon(pm)


def _looks_like_html(s: str) -> bool:
    t = (s or "").lstrip().lower()
    if not t:
        return False
    return (
        t.startswith("<!doctype")
        or t.startswith("<html")
        or t.startswith("<p")
        or "<span" in t
        or "<br" in t
        or "<div" in t
    )


def _strip_highlight_html(html: str) -> str:
    """
    기존 데이터(HTML)에 남아있는 하이라이트(배경색) 마크업 제거.
    - background-color / background CSS 제거
    - 빈 style="" 정리
    """
    if not html:
        return html
    if not _looks_like_html(html):
        return html

    s = html
    s = re.sub(r'background-color\s*:\s*#[0-9a-fA-F]{3,8}\s*;?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'background-color\s*:\s*rgba?\([^)]+\)\s*;?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'background\s*:\s*#[0-9a-fA-F]{3,8}\s*;?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'background\s*:\s*rgba?\([^)]+\)\s*;?', '', s, flags=re.IGNORECASE)

    s = re.sub(r'style="\s*;+\s*"', '', s, flags=re.IGNORECASE)
    s = re.sub(r'style="\s*"', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\sstyle=""', '', s, flags=re.IGNORECASE)

    def _tidy_style(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        inner = re.sub(r'\s*;+\s*', '; ', inner).strip()
        inner = inner.strip("; ").strip()
        return f'style="{inner}"' if inner else ""

    s = re.sub(r'style="([^"]*?)"', _tidy_style, s, flags=re.IGNORECASE)
    return s


# ---------------------------
# FlowLayout (auto wrap)
# ---------------------------
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=-1):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._item_list: List[QWidgetItem] = []

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective_rect = rect.adjusted(left, top, -right, -bottom)
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        space_x = self.spacing()
        space_y = self.spacing()
        if space_x < 0:
            space_x = 6
        if space_y < 0:
            space_y = 6

        for item in self._item_list:
            wid = item.widget()
            if wid is not None and not wid.isVisible():
                continue

            item_size = item.sizeHint()
            next_x = x + item_size.width() + space_x

            if next_x - space_x > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + space_y
                next_x = x + item_size.width() + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_size.height())

        return (y + line_height - rect.y()) + bottom


# ---------------------------
# Collapsible caption overlay
# ---------------------------
class CollapsibleCaptionEdit(QPlainTextEdit):
    expandedChanged = pyqtSignal(bool)

    def __init__(self, parent=None, collapsed_h: int = 28, expanded_h: int = 84):
        super().__init__(parent)
        self._collapsed_h = int(collapsed_h)
        self._expanded_h = int(expanded_h)
        self._expanded = False

        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self.setFixedHeight(self._collapsed_h)
        self.setStyleSheet("""
            QPlainTextEdit {
                background: rgba(255,255,255,235);
                border: 1px solid #9A9A9A;
                border-radius: 8px;
                padding: 6px 10px;
                color: #222;
            }
            QPlainTextEdit:focus {
                border: 1px solid #5A8DFF;
            }
        """)

    def setPlaceholderTextCompat(self, text: str) -> None:
        try:
            self.setPlaceholderText(text)
        except Exception:
            pass

    def expand(self) -> None:
        if self._expanded:
            return
        self._expanded = True
        self.setFixedHeight(self._expanded_h)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.expandedChanged.emit(True)

    def collapse(self) -> None:
        if not self._expanded:
            return
        self._expanded = False
        self.setFixedHeight(self._collapsed_h)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.expandedChanged.emit(False)

    def enterEvent(self, event) -> None:
        self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self.hasFocus():
            self.collapse()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self.expand()
        super().mousePressEvent(event)

    def focusInEvent(self, event) -> None:
        self.expand()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        QTimer.singleShot(0, self._collapse_if_not_hovered)

    def _collapse_if_not_hovered(self) -> None:
        if self.hasFocus():
            return
        if not self.underMouse():
            self.collapse()


# ---------------------------
# Data Models
# ---------------------------
Strokes = List[Dict[str, Any]]
Checklist = List[Dict[str, Any]]


def _normalize_strokes(raw: Any) -> Strokes:
    if not raw:
        return []

    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        out: Strokes = []
        for s in raw:
            try:
                color = str(s.get("color", COLOR_RED))
                width = float(s.get("width", 3.0))
                pts = s.get("points", [])
                if not isinstance(pts, list):
                    pts = []
                out.append({"color": color, "width": width, "points": pts})
            except Exception:
                continue
        return out

    if isinstance(raw, list) and (len(raw) == 0 or isinstance(raw[0], list)):
        out2: Strokes = []
        for stroke in raw:
            if not isinstance(stroke, list):
                continue
            out2.append({"color": COLOR_RED, "width": 3.0, "points": stroke})
        return out2

    return []


def _default_checklist() -> Checklist:
    return [{"q": q, "checked": False, "note": ""} for q in DEFAULT_CHECK_QUESTIONS]


def _normalize_checklist(raw: Any) -> Checklist:
    base = _default_checklist()
    if not isinstance(raw, list):
        return base
    for i in range(min(len(base), len(raw))):
        item = raw[i]
        if isinstance(item, dict):
            base[i]["checked"] = bool(item.get("checked", False))
            base[i]["note"] = str(item.get("note", ""))
    return base


@dataclass
class Page:
    id: str
    image_a_path: str
    image_b_path: str
    image_a_caption: str
    image_b_caption: str
    strokes_a: Strokes
    strokes_b: Strokes
    note_text: str
    stock_name: str
    ticker: str
    checklist: Checklist
    created_at: int
    updated_at: int


@dataclass
class Item:
    id: str
    name: str
    pages: List[Page]
    last_page_index: int = 0
    created_at: int = 0
    updated_at: int = 0


@dataclass
class Category:
    id: str
    name: str
    categories: List["Category"]
    items: List[Item]
    created_at: int = 0
    updated_at: int = 0


class NoteDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.data: Dict[str, Any] = {}
        self.ui_state: Dict[str, Any] = {}
        self.global_ideas: str = ""  # HTML
        self.root: Category = self._default_root()
        self.load()

    # ---------------- Default / Migration ----------------
    def _default_root(self) -> Category:
        now = _now_epoch()
        # Default: root -> General -> Item 1
        pg = self.new_page()
        it = Item(id=_uuid(), name="Item 1", pages=[pg], last_page_index=0, created_at=now, updated_at=now)
        gen = Category(id=_uuid(), name="General", categories=[], items=[it], created_at=now, updated_at=now)
        return Category(id=ROOT_CATEGORY_ID, name="ROOT", categories=[gen], items=[], created_at=now, updated_at=now)

    @staticmethod
    def new_page() -> Page:
        now = _now_epoch()
        return Page(
            id=_uuid(),
            image_a_path="",
            image_b_path="",
            image_a_caption="",
            image_b_caption="",
            strokes_a=[],
            strokes_b=[],
            note_text="",
            stock_name="",
            ticker="",
            checklist=_default_checklist(),
            created_at=now,
            updated_at=now,
        )

    def _default_data(self) -> Dict[str, Any]:
        now = _now_epoch()
        root = self._serialize_category(self._default_root())
        return {
            "version": "0.6.0",
            "created_at": now,
            "updated_at": now,
            "root": root,
            "global_ideas": "",
            "ui_state": {
                "selected_category_id": "",   # optional
                "selected_item_id": "",       # optional
                "current_page_index": 0,
                "desc_visible": True,
                "global_ideas_visible": False,
                "trace_visible": True,
                "page_splitter_sizes": None,      # (charts vs notes)
                "notes_splitter_sizes": None,     # (notes vs ideas) - within notes
                "img_vsplit_sizes": None,         # (A vs B)
                "main_splitter_sizes": None,      # (left tree vs right)
                "right_vsplit_sizes": None,       # (main vs trace)
            },
        }

    def load(self) -> None:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

        if not self.data:
            self.data = self._default_data()

        # Migration: v0.5.x "steps" -> v0.6.0 structure
        if "root" not in self.data and isinstance(self.data.get("steps", None), list):
            self.data = self._migrate_from_steps(self.data)

        self.ui_state = self.data.get("ui_state", {})
        if not isinstance(self.ui_state, dict):
            self.ui_state = {}

        self.ui_state.setdefault("desc_visible", True)
        self.ui_state.setdefault("global_ideas_visible", False)
        self.ui_state.setdefault("trace_visible", True)
        self.ui_state.setdefault("current_page_index", 0)

        self.global_ideas = str(self.data.get("global_ideas", "") or "")

        root_raw = self.data.get("root", None)
        if isinstance(root_raw, dict):
            self.root = self._parse_category(root_raw, force_root=True)
        else:
            self.root = self._default_root()

        # ensure at least one item exists
        if not self._any_item_exists():
            self.root = self._default_root()

    def save(self) -> bool:
        self.data["version"] = "0.6.0"
        self.data["updated_at"] = _now_epoch()
        self.data["root"] = self._serialize_category(self.root)
        self.data["ui_state"] = self.ui_state
        self.data["global_ideas"] = self.global_ideas

        ok = _safe_write_json(self.db_path, self.data)
        self.data["_last_save_ok"] = bool(ok)
        if not ok:
            self.data["_last_save_failed_at"] = _now_epoch()
        return ok

    # ---------------- Migration from v0.5.x ----------------
    def _migrate_from_steps(self, old: Dict[str, Any]) -> Dict[str, Any]:
        """
        v0.5.x format:
          steps: [{id,name,category,last_page_index,pages:[...]}]
        -> v0.6.0 root/categories/items
        """
        now = _now_epoch()
        steps = old.get("steps", [])
        if not isinstance(steps, list):
            steps = []

        # create root
        root = Category(id=ROOT_CATEGORY_ID, name="ROOT", categories=[], items=[], created_at=now, updated_at=now)

        # categories by name at root level
        cat_map: Dict[str, Category] = {}

        def get_or_create_cat(cat_name: str) -> Category:
            cat_name = (cat_name or "").strip() or "General"
            if cat_name in cat_map:
                return cat_map[cat_name]
            c = Category(id=_uuid(), name=cat_name, categories=[], items=[], created_at=now, updated_at=now)
            cat_map[cat_name] = c
            root.categories.append(c)
            return c

        for s in steps:
            try:
                cat_name = str(s.get("category", "General") or "General").strip() or "General"
                item_name = str(s.get("name", "Item") or "Item")
                item_id = str(s.get("id", _uuid()))
                last_idx = int(s.get("last_page_index", 0))

                pages_raw = s.get("pages", [])
                if not isinstance(pages_raw, list):
                    pages_raw = []

                pages: List[Page] = []
                for p in pages_raw:
                    image_a_path = str(p.get("image_a_path", p.get("image_path", "")) or "")
                    image_b_path = str(p.get("image_b_path", "")) or ""
                    image_a_caption = str(p.get("image_a_caption", p.get("image_caption", "")) or "")
                    image_b_caption = str(p.get("image_b_caption", "")) or ""

                    raw_strokes_a = p.get("strokes_a", None)
                    if raw_strokes_a is None:
                        raw_strokes_a = p.get("strokes", None)
                    if raw_strokes_a is None:
                        raw_strokes_a = p.get("annotations", [])

                    raw_strokes_b = p.get("strokes_b", None)
                    if raw_strokes_b is None:
                        raw_strokes_b = []

                    strokes_a = _normalize_strokes(raw_strokes_a)
                    strokes_b = _normalize_strokes(raw_strokes_b)
                    checklist = _normalize_checklist(p.get("checklist", None))

                    pages.append(
                        Page(
                            id=str(p.get("id", _uuid())),
                            image_a_path=image_a_path,
                            image_b_path=image_b_path,
                            image_a_caption=image_a_caption,
                            image_b_caption=image_b_caption,
                            strokes_a=strokes_a,
                            strokes_b=strokes_b,
                            note_text=str(p.get("note_text", "")),
                            stock_name=str(p.get("stock_name", "")),
                            ticker=str(p.get("ticker", "")),
                            checklist=checklist,
                            created_at=int(p.get("created_at", now)),
                            updated_at=int(p.get("updated_at", now)),
                        )
                    )

                if not pages:
                    pages = [self.new_page()]

                it = Item(
                    id=item_id,
                    name=item_name,
                    pages=pages,
                    last_page_index=max(0, min(last_idx, len(pages) - 1)),
                    created_at=now,
                    updated_at=now,
                )
                get_or_create_cat(cat_name).items.append(it)
            except Exception:
                continue

        # ui_state carry-over (best-effort)
        ui = old.get("ui_state", {})
        if not isinstance(ui, dict):
            ui = {}
        new_ui = {
            "selected_category_id": "",
            "selected_item_id": "",
            "current_page_index": int(ui.get("current_page_index", 0)) if isinstance(ui.get("current_page_index", 0), int) else 0,
            "desc_visible": bool(ui.get("desc_visible", True)),
            "global_ideas_visible": bool(ui.get("global_ideas_visible", False)),
            "trace_visible": bool(ui.get("trace_visible", True)),
            "page_splitter_sizes": ui.get("page_splitter_sizes", None),
            "notes_splitter_sizes": ui.get("notes_splitter_sizes", None),
            "img_vsplit_sizes": None,
            "main_splitter_sizes": None,
            "right_vsplit_sizes": ui.get("right_vsplit_sizes", None),
        }

        # pick first item as selection
        first_item_id = ""
        first_cat_id = ""
        for c in root.categories:
            if c.items:
                first_cat_id = c.id
                first_item_id = c.items[0].id
                break
        new_ui["selected_category_id"] = first_cat_id
        new_ui["selected_item_id"] = first_item_id

        return {
            "version": "0.6.0",
            "created_at": int(old.get("created_at", now)) if isinstance(old.get("created_at", now), int) else now,
            "updated_at": now,
            "root": self._serialize_category(root),
            "global_ideas": str(old.get("global_ideas", "") or ""),
            "ui_state": new_ui,
        }

    # ---------------- Serialize/Parse ----------------
    def _parse_category(self, raw: Dict[str, Any], force_root: bool = False) -> Category:
        now = _now_epoch()
        cid = str(raw.get("id", _uuid()))
        if force_root:
            cid = ROOT_CATEGORY_ID
        name = str(raw.get("name", "Category") or "Category")
        cats_raw = raw.get("categories", [])
        items_raw = raw.get("items", [])

        cats: List[Category] = []
        if isinstance(cats_raw, list):
            for c in cats_raw:
                if isinstance(c, dict):
                    cats.append(self._parse_category(c, force_root=False))

        items: List[Item] = []
        if isinstance(items_raw, list):
            for it in items_raw:
                if not isinstance(it, dict):
                    continue
                pages_raw = it.get("pages", [])
                pages: List[Page] = []
                if isinstance(pages_raw, list):
                    for p in pages_raw:
                        if not isinstance(p, dict):
                            continue
                        pages.append(
                            Page(
                                id=str(p.get("id", _uuid())),
                                image_a_path=str(p.get("image_a_path", "") or ""),
                                image_b_path=str(p.get("image_b_path", "") or ""),
                                image_a_caption=str(p.get("image_a_caption", "") or ""),
                                image_b_caption=str(p.get("image_b_caption", "") or ""),
                                strokes_a=_normalize_strokes(p.get("strokes_a", [])),
                                strokes_b=_normalize_strokes(p.get("strokes_b", [])),
                                note_text=str(p.get("note_text", "") or ""),
                                stock_name=str(p.get("stock_name", "") or ""),
                                ticker=str(p.get("ticker", "") or ""),
                                checklist=_normalize_checklist(p.get("checklist", None)),
                                created_at=int(p.get("created_at", now)),
                                updated_at=int(p.get("updated_at", now)),
                            )
                        )
                if not pages:
                    pages = [self.new_page()]
                items.append(
                    Item(
                        id=str(it.get("id", _uuid())),
                        name=str(it.get("name", "Item") or "Item"),
                        pages=pages,
                        last_page_index=int(it.get("last_page_index", 0)),
                        created_at=int(it.get("created_at", now)),
                        updated_at=int(it.get("updated_at", now)),
                    )
                )

        return Category(
            id=cid,
            name=name,
            categories=cats,
            items=items,
            created_at=int(raw.get("created_at", now)),
            updated_at=int(raw.get("updated_at", now)),
        )

    def _serialize_category(self, cat: Category) -> Dict[str, Any]:
        return {
            "id": cat.id,
            "name": cat.name,
            "created_at": int(cat.created_at or 0),
            "updated_at": int(cat.updated_at or 0),
            "categories": [self._serialize_category(c) for c in cat.categories],
            "items": [self._serialize_item(it) for it in cat.items],
        }

    def _serialize_item(self, it: Item) -> Dict[str, Any]:
        return {
            "id": it.id,
            "name": it.name,
            "last_page_index": int(it.last_page_index),
            "created_at": int(it.created_at or 0),
            "updated_at": int(it.updated_at or 0),
            "pages": [
                {
                    "id": pg.id,
                    "image_a_path": pg.image_a_path,
                    "image_b_path": pg.image_b_path,
                    "image_a_caption": pg.image_a_caption,
                    "image_b_caption": pg.image_b_caption,
                    "strokes_a": pg.strokes_a,
                    "strokes_b": pg.strokes_b,
                    "note_text": pg.note_text,
                    "stock_name": pg.stock_name,
                    "ticker": pg.ticker,
                    "checklist": pg.checklist,
                    "created_at": int(pg.created_at),
                    "updated_at": int(pg.updated_at),
                }
                for pg in it.pages
            ],
        }

    # ---------------- Find / Ops ----------------
    def _any_item_exists(self) -> bool:
        return self._find_first_item(self.root) is not None

    def _find_first_item(self, cat: Category) -> Optional[Tuple[Item, Category]]:
        for it in cat.items:
            return it, cat
        for c in cat.categories:
            r = self._find_first_item(c)
            if r is not None:
                return r
        return None

    def find_category(self, category_id: str) -> Optional[Category]:
        if not category_id:
            return None
        return self._find_category_rec(self.root, category_id)

    def _find_category_rec(self, cat: Category, category_id: str) -> Optional[Category]:
        if cat.id == category_id:
            return cat
        for c in cat.categories:
            r = self._find_category_rec(c, category_id)
            if r is not None:
                return r
        return None

    def find_item(self, item_id: str) -> Optional[Tuple[Item, Category]]:
        if not item_id:
            return None
        return self._find_item_rec(self.root, item_id)

    def _find_item_rec(self, cat: Category, item_id: str) -> Optional[Tuple[Item, Category]]:
        for it in cat.items:
            if it.id == item_id:
                return it, cat
        for c in cat.categories:
            r = self._find_item_rec(c, item_id)
            if r is not None:
                return r
        return None

    def find_parent_of_category(self, category_id: str) -> Optional[Category]:
        if category_id == ROOT_CATEGORY_ID:
            return None
        return self._find_parent_cat_rec(self.root, category_id)

    def _find_parent_cat_rec(self, cat: Category, target_id: str) -> Optional[Category]:
        for c in cat.categories:
            if c.id == target_id:
                return cat
        for c in cat.categories:
            r = self._find_parent_cat_rec(c, target_id)
            if r is not None:
                return r
        return None

    def add_category(self, parent_category_id: str, name: str) -> Category:
        now = _now_epoch()
        parent = self.find_category(parent_category_id) or self.root
        new_cat = Category(id=_uuid(), name=name, categories=[], items=[], created_at=now, updated_at=now)
        parent.categories.append(new_cat)
        parent.updated_at = now
        return new_cat

    def add_item(self, parent_category_id: str, name: str) -> Item:
        now = _now_epoch()
        parent = self.find_category(parent_category_id) or self.root
        it = Item(id=_uuid(), name=name, pages=[self.new_page()], last_page_index=0, created_at=now, updated_at=now)
        parent.items.append(it)
        parent.updated_at = now
        return it

    def delete_item(self, item_id: str) -> bool:
        found = self.find_item(item_id)
        if not found:
            return False
        it, parent = found
        if len(parent.items) <= 0:
            return False
        parent.items = [x for x in parent.items if x.id != it.id]
        parent.updated_at = _now_epoch()
        return True

    def delete_category_recursive(self, category_id: str) -> bool:
        if category_id == ROOT_CATEGORY_ID:
            return False
        parent = self.find_parent_of_category(category_id)
        if parent is None:
            return False
        parent.categories = [c for c in parent.categories if c.id != category_id]
        parent.updated_at = _now_epoch()
        return True

    def move_item(self, item_id: str, direction: int) -> bool:
        found = self.find_item(item_id)
        if not found:
            return False
        it, parent = found
        idx = -1
        for i, x in enumerate(parent.items):
            if x.id == it.id:
                idx = i
                break
        if idx < 0:
            return False
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(parent.items):
            return False
        parent.items[idx], parent.items[new_idx] = parent.items[new_idx], parent.items[idx]
        parent.updated_at = _now_epoch()
        return True

    def move_category(self, category_id: str, direction: int) -> bool:
        if category_id == ROOT_CATEGORY_ID:
            return False
        parent = self.find_parent_of_category(category_id)
        if parent is None:
            return False
        idx = -1
        for i, c in enumerate(parent.categories):
            if c.id == category_id:
                idx = i
                break
        if idx < 0:
            return False
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(parent.categories):
            return False
        parent.categories[idx], parent.categories[new_idx] = parent.categories[new_idx], parent.categories[idx]
        parent.updated_at = _now_epoch()
        return True


# ---------------------------
# Image view with zoom/pan + strokes
# ---------------------------
class ZoomPanAnnotateView(QGraphicsView):
    imageDropped = pyqtSignal(str)
    strokesChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._has_image: bool = False

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._zoom_factor_step = 1.25
        self._min_scale = 0.05
        self._max_scale = 20.0

        self._draw_mode: bool = False
        self._is_drawing: bool = False

        self._pen_color = QColor(COLOR_RED)
        self._pen_width = 3.0

        self._current_path: Optional[QPainterPath] = None
        self._current_item: Optional[QGraphicsPathItem] = None
        self._current_points: List[List[float]] = []
        self._stroke_start: Optional[QPointF] = None
        self._stroke_color_hex: str = COLOR_RED
        self._stroke_width: float = 3.0

        self._strokes: Strokes = []
        self._stroke_items: List[QGraphicsPathItem] = []

        self.set_mode_pan()

    def set_pen(self, color_hex: str, width: float) -> None:
        c = QColor(color_hex)
        if not c.isValid():
            c = QColor(COLOR_RED)
        self._pen_color = c
        self._pen_width = float(width)

    def _make_pen(self, color_hex: str, width: float) -> QPen:
        c = QColor(color_hex)
        if not c.isValid():
            c = QColor(COLOR_RED)
        pen = QPen(c, float(width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def set_mode_draw(self) -> None:
        self._draw_mode = True
        self.setDragMode(QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.CrossCursor)

    def set_mode_pan(self) -> None:
        self._draw_mode = False
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.viewport().setCursor(Qt.OpenHandCursor)

    def clear_image(self) -> None:
        self._clear_strokes_internal(emit_signal=False)
        self._scene.clear()
        self._pixmap_item = None
        self._has_image = False
        self.resetTransform()

    def set_image_path(self, abs_path: str) -> None:
        pm = QPixmap(abs_path)
        if pm.isNull():
            self.clear_image()
            return
        self._set_pixmap(pm)

    def _set_pixmap(self, pm: QPixmap) -> None:
        self._clear_strokes_internal(emit_signal=False)
        self._scene.clear()

        self._pixmap_item = self._scene.addPixmap(pm)
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._pixmap_item.setZValue(0)

        self._has_image = True
        self._scene.setSceneRect(QRectF(pm.rect()))
        self.resetTransform()
        self.fit_to_view()

    def fit_to_view(self) -> None:
        if not self._pixmap_item:
            self.resetTransform()
            return
        rect = self._pixmap_item.boundingRect()
        if rect.isNull():
            return
        self.resetTransform()
        self.fitInView(rect, Qt.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        if not self._has_image:
            return

        current_scale = self.transform().m11()
        if event.angleDelta().y() > 0:
            target = current_scale * self._zoom_factor_step
        else:
            target = current_scale / self._zoom_factor_step

        if target < self._min_scale or target > self._max_scale:
            return

        if event.angleDelta().y() > 0:
            self.scale(self._zoom_factor_step, self._zoom_factor_step)
        else:
            inv = 1.0 / self._zoom_factor_step
            self.scale(inv, inv)

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

    def get_strokes(self) -> Strokes:
        return self._strokes

    def set_strokes(self, strokes: Strokes) -> None:
        self._clear_strokes_internal(emit_signal=False)
        self._strokes = strokes or []

        if not self._has_image:
            return

        for s in self._strokes:
            pts = s.get("points", [])
            if not isinstance(pts, list) or len(pts) < 2:
                continue
            color = str(s.get("color", COLOR_RED))
            width = float(s.get("width", 3.0))

            path = QPainterPath(QPointF(pts[0][0], pts[0][1]))
            for pt in pts[1:]:
                path.lineTo(QPointF(pt[0], pt[1]))

            item = QGraphicsPathItem(path)
            item.setPen(self._make_pen(color, width))
            item.setZValue(10)
            self._scene.addItem(item)
            self._stroke_items.append(item)

    def clear_strokes(self) -> None:
        self._clear_strokes_internal(emit_signal=True)

    def _clear_strokes_internal(self, emit_signal: bool) -> None:
        for it in list(self._stroke_items):
            try:
                self._scene.removeItem(it)
            except Exception:
                pass

        self._stroke_items = []
        self._strokes = []

        self._is_drawing = False
        self._current_item = None
        self._current_path = None
        self._current_points = []
        self._stroke_start = None

        if emit_signal:
            self.strokesChanged.emit()

    def mousePressEvent(self, event) -> None:
        if self._draw_mode and self._has_image and event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            if not self._point_inside_pixmap(scene_pos):
                return
            self._start_stroke(scene_pos)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._draw_mode and self._is_drawing and self._has_image:
            scene_pos = self.mapToScene(event.pos())
            if not self._point_inside_pixmap(scene_pos):
                return
            shift = bool(event.modifiers() & Qt.ShiftModifier)
            self._append_stroke(scene_pos, shift=shift)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._draw_mode and self._is_drawing and event.button() == Qt.LeftButton:
            self._finish_stroke()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _point_inside_pixmap(self, pt: QPointF) -> bool:
        if not self._pixmap_item:
            return False
        return self._pixmap_item.boundingRect().contains(pt)

    def _start_stroke(self, pt: QPointF) -> None:
        self._is_drawing = True
        self._stroke_start = pt

        self._stroke_color_hex = self._pen_color.name().upper()
        self._stroke_width = float(self._pen_width)

        self._current_path = QPainterPath(pt)
        self._current_points = [[float(pt.x()), float(pt.y())]]

        item = QGraphicsPathItem(self._current_path)
        item.setPen(self._make_pen(self._stroke_color_hex, self._stroke_width))
        item.setZValue(10)
        self._scene.addItem(item)
        self._current_item = item

    def _append_stroke(self, pt: QPointF, shift: bool) -> None:
        if not self._current_item or not self._stroke_start:
            return

        if shift:
            start = self._stroke_start
            path = QPainterPath(start)
            path.lineTo(pt)
            self._current_item.setPath(path)
            self._current_points = [[float(start.x()), float(start.y())], [float(pt.x()), float(pt.y())]]
            return

        if not self._current_path:
            self._current_path = QPainterPath(self._stroke_start)

        last = self._current_points[-1]
        dx = pt.x() - last[0]
        dy = pt.y() - last[1]
        if (dx * dx + dy * dy) < 4.0:
            return

        self._current_path.lineTo(pt)
        self._current_item.setPath(self._current_path)
        self._current_points.append([float(pt.x()), float(pt.y())])

    def _finish_stroke(self) -> None:
        if not self._current_item or len(self._current_points) < 2:
            if self._current_item:
                try:
                    self._scene.removeItem(self._current_item)
                except Exception:
                    pass
            self._reset_current()
            return

        self._stroke_items.append(self._current_item)
        self._strokes.append(
            {"color": self._stroke_color_hex, "width": self._stroke_width, "points": self._current_points}
        )

        self._reset_current()
        self.strokesChanged.emit()

    def _reset_current(self) -> None:
        self._is_drawing = False
        self._current_item = None
        self._current_path = None
        self._current_points = []
        self._stroke_start = None


# ---------------------------
# Main Window
# ---------------------------
class MainWindow(QMainWindow):
    NODE_TYPE_ROLE = Qt.UserRole + 2001   # "category" or "item"
    CATEGORY_ID_ROLE = Qt.UserRole + 2002
    ITEM_ID_ROLE = Qt.UserRole + 2003

    TRACE_MAX_LINES = 1200

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1460, 960)

        self.db = NoteDB(DEFAULT_DB_PATH)

        self.current_category_id: str = self.db.ui_state.get("selected_category_id", "") or ""
        self.current_item_id: str = self.db.ui_state.get("selected_item_id", "") or ""
        self.current_page_index: int = int(self.db.ui_state.get("current_page_index", 0) or 0)

        self._loading_ui: bool = False
        self._active_rich_edit: Optional[QTextEdit] = None

        self._desc_visible: bool = bool(self.db.ui_state.get("desc_visible", True))
        self._trace_visible: bool = bool(self.db.ui_state.get("trace_visible", True))

        self.viewer_a: Optional[ZoomPanAnnotateView] = None
        self.viewer_b: Optional[ZoomPanAnnotateView] = None
        self._active_pane: str = "A"
        self._pane_ui: Dict[str, Dict[str, Any]] = {}

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_page_fields_to_model_and_save)

        self._last_save_warn_ts: float = 0.0
        self._save_warn_cooldown_sec: float = 10.0

        self._build_ui()
        self._build_pane_overlays()

        # Restore selection to a valid item
        self._ensure_valid_selection()

        # Apply UI state
        self._apply_splitter_sizes_from_state()

        self._refresh_tree(select_current=True)
        self._load_current_item_page_to_ui()
        self._load_global_ideas_to_ui()

        ideas_vis = bool(self.db.ui_state.get("global_ideas_visible", False))
        self._set_global_ideas_visible(ideas_vis, persist=False)
        self._set_desc_visible(bool(self.db.ui_state.get("desc_visible", True)), persist=False)
        self._set_trace_visible(bool(self.db.ui_state.get("trace_visible", True)), persist=False)

        # Shortcuts
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_prev_page)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.go_next_page)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_page)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.force_save)

        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.btn_fmt_bold.toggle())
        QShortcut(QKeySequence("Ctrl+I"), self, activated=lambda: self.btn_fmt_italic.toggle())
        QShortcut(QKeySequence("Ctrl+U"), self, activated=lambda: self.btn_fmt_underline.toggle())

        if self.viewer_a is not None:
            QShortcut(QKeySequence("Ctrl+V"), self.viewer_a, activated=lambda: self.paste_image_from_clipboard("A"))
        if self.viewer_b is not None:
            QShortcut(QKeySequence("Ctrl+V"), self.viewer_b, activated=lambda: self.paste_image_from_clipboard("B"))

        self._update_text_area_layout()
        QTimer.singleShot(0, self._post_init_layout_fix)

        self.trace("App initialized (v0.6.0)", "INFO")

    # ---------------- Trace helpers ----------------
    def trace(self, msg: str, level: str = "INFO") -> None:
        try:
            if not hasattr(self, "trace_edit") or self.trace_edit is None:
                return
            ts = time.strftime("%H:%M:%S")
            self.trace_edit.appendPlainText(f"[{ts}] [{level}] {msg}")

            doc = self.trace_edit.document()
            if doc.blockCount() > self.TRACE_MAX_LINES:
                cur = self.trace_edit.textCursor()
                cur.beginEditBlock()
                try:
                    while doc.blockCount() > self.TRACE_MAX_LINES:
                        cur.movePosition(cur.Start)
                        cur.select(cur.LineUnderCursor)
                        cur.removeSelectedText()
                        cur.deleteChar()
                finally:
                    cur.endEditBlock()
        except Exception:
            pass

    def _copy_trace_to_clipboard(self) -> None:
        try:
            QApplication.clipboard().setText(self.trace_edit.toPlainText())
            self.trace("Trace copied to clipboard", "INFO")
        except Exception:
            pass

    def _clear_trace(self) -> None:
        try:
            self.trace_edit.clear()
            self.trace("Trace cleared", "INFO")
        except Exception:
            pass

    # ---------------- Selection validity ----------------
    def _ensure_valid_selection(self) -> None:
        # If current item missing, select first item in tree
        found = self.db.find_item(self.current_item_id)
        if found is None:
            first = self.db._find_first_item(self.db.root)
            if first is not None:
                it, parent = first
                self.current_item_id = it.id
                self.current_category_id = parent.id
                self.current_page_index = max(0, min(it.last_page_index, len(it.pages) - 1))
            else:
                # fallback: reset to default
                self.db.root = self.db._default_root()
                it, parent = self.db._find_first_item(self.db.root)
                self.current_item_id = it.id
                self.current_category_id = parent.id
                self.current_page_index = 0

    # ---------------- UI building ----------------
    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main: left tree / right content (inside right_vsplit with trace)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        controls = QWidget()
        cl = FlowLayout(controls, margin=0, spacing=6)

        self.btn_add_folder = QToolButton()
        self.btn_add_folder.setText("+ Folder")
        self.btn_add_item = QToolButton()
        self.btn_add_item.setText("+ Item")
        self.btn_rename_node = QToolButton()
        self.btn_rename_node.setText("Rename")
        self.btn_delete_node = QToolButton()
        self.btn_delete_node.setText("Delete")
        self.btn_move_up = QToolButton()
        self.btn_move_up.setText("↑")
        self.btn_move_up.setToolTip("Move Up")
        self.btn_move_down = QToolButton()
        self.btn_move_down.setText("↓")
        self.btn_move_down.setToolTip("Move Down")

        self.btn_add_folder.clicked.connect(self.add_folder)
        self.btn_add_item.clicked.connect(self.add_item)
        self.btn_rename_node.clicked.connect(self.rename_node)
        self.btn_delete_node.clicked.connect(self.delete_node)
        self.btn_move_up.clicked.connect(lambda: self.move_node(-1))
        self.btn_move_down.clicked.connect(lambda: self.move_node(+1))

        cl.addWidget(self.btn_add_folder)
        cl.addWidget(self.btn_add_item)
        cl.addWidget(self.btn_rename_node)
        cl.addWidget(self.btn_delete_node)
        cl.addWidget(self.btn_move_up)
        cl.addWidget(self.btn_move_down)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection_changed)

        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        left_layout.addWidget(controls)
        left_layout.addWidget(self.tree, 1)

        # Right: vertical split (main content / trace)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.right_vsplit = QSplitter(Qt.Vertical)
        self.right_vsplit.setChildrenCollapsible(False)

        # Main content widget
        main_content = QWidget()
        main_content_l = QVBoxLayout(main_content)
        main_content_l.setContentsMargins(0, 0, 0, 0)
        main_content_l.setSpacing(8)

        # page_splitter: charts(left) vs notes(right)
        self.page_splitter = QSplitter(Qt.Horizontal)
        self.page_splitter.setChildrenCollapsible(False)

        # ---------------- Charts panel (left): Vertical A/B ----------------
        self.img_panel = QWidget()
        img_layout = QVBoxLayout(self.img_panel)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(6)

        meta_widget = QWidget()
        meta_flow = FlowLayout(meta_widget, margin=0, spacing=6)

        meta_flow.addWidget(QLabel("Name:"))
        self.edit_stock_name = QLineEdit()
        self.edit_stock_name.setPlaceholderText("e.g., Apple Inc.")
        self.edit_stock_name.setFixedWidth(220)
        self.edit_stock_name.textChanged.connect(self._on_page_field_changed)
        meta_flow.addWidget(self.edit_stock_name)

        meta_flow.addWidget(QLabel("Ticker:"))
        self.edit_ticker = QLineEdit()
        self.edit_ticker.setPlaceholderText("e.g., AAPL")
        self.edit_ticker.setFixedWidth(120)
        self.edit_ticker.textChanged.connect(self._on_page_field_changed)
        meta_flow.addWidget(self.edit_ticker)

        self.btn_copy_ticker = QToolButton()
        self.btn_copy_ticker.setIcon(_make_copy_icon(16))
        self.btn_copy_ticker.setToolTip("Copy ticker to clipboard")
        self.btn_copy_ticker.setFixedSize(30, 26)
        self.btn_copy_ticker.clicked.connect(self.copy_ticker)
        meta_flow.addWidget(self.btn_copy_ticker)

        img_layout.addWidget(meta_widget)

        # Chart controls A/B (top rows inside each pane)
        self.img_vsplit = QSplitter(Qt.Vertical)
        self.img_vsplit.setChildrenCollapsible(False)

        # Pane A
        paneA = QWidget()
        paneA_l = QVBoxLayout(paneA)
        paneA_l.setContentsMargins(0, 0, 0, 0)
        paneA_l.setSpacing(6)

        barA = QWidget()
        barA_l = FlowLayout(barA, margin=0, spacing=6)
        lblA = QLabel("Chart A")
        lblA.setStyleSheet("font-weight: 700;")
        barA_l.addWidget(lblA)

        self.btn_open_a = QPushButton("Open A")
        self.btn_paste_a = QPushButton("Paste A")
        self.btn_clear_a = QPushButton("Clr A")
        self.btn_fit_a = QPushButton("Fit A")
        self.btn_open_a.clicked.connect(lambda: self.set_image_via_dialog("A"))
        self.btn_paste_a.clicked.connect(lambda: self.paste_image_from_clipboard("A"))
        self.btn_clear_a.clicked.connect(lambda: self.clear_image("A"))
        self.btn_fit_a.clicked.connect(lambda: self.reset_image_view("A"))

        barA_l.addWidget(self.btn_open_a)
        barA_l.addWidget(self.btn_paste_a)
        barA_l.addWidget(self.btn_clear_a)
        barA_l.addWidget(self.btn_fit_a)
        paneA_l.addWidget(barA)

        self.viewer_a = ZoomPanAnnotateView()
        self.viewer_a.imageDropped.connect(lambda p: self._on_image_dropped("A", p))
        self.viewer_a.strokesChanged.connect(self._on_page_field_changed)
        self.viewer_a.viewport().installEventFilter(self)
        paneA_l.addWidget(self.viewer_a, 1)

        # Pane B
        paneB = QWidget()
        paneB_l = QVBoxLayout(paneB)
        paneB_l.setContentsMargins(0, 0, 0, 0)
        paneB_l.setSpacing(6)

        barB = QWidget()
        barB_l = FlowLayout(barB, margin=0, spacing=6)
        lblB = QLabel("Chart B")
        lblB.setStyleSheet("font-weight: 700;")
        barB_l.addWidget(lblB)

        self.btn_open_b = QPushButton("Open B")
        self.btn_paste_b = QPushButton("Paste B")
        self.btn_clear_b = QPushButton("Clr B")
        self.btn_fit_b = QPushButton("Fit B")
        self.btn_open_b.clicked.connect(lambda: self.set_image_via_dialog("B"))
        self.btn_paste_b.clicked.connect(lambda: self.paste_image_from_clipboard("B"))
        self.btn_clear_b.clicked.connect(lambda: self.clear_image("B"))
        self.btn_fit_b.clicked.connect(lambda: self.reset_image_view("B"))

        barB_l.addWidget(self.btn_open_b)
        barB_l.addWidget(self.btn_paste_b)
        barB_l.addWidget(self.btn_clear_b)
        barB_l.addWidget(self.btn_fit_b)
        paneB_l.addWidget(barB)

        self.viewer_b = ZoomPanAnnotateView()
        self.viewer_b.imageDropped.connect(lambda p: self._on_image_dropped("B", p))
        self.viewer_b.strokesChanged.connect(self._on_page_field_changed)
        self.viewer_b.viewport().installEventFilter(self)
        paneB_l.addWidget(self.viewer_b, 1)

        self.img_vsplit.addWidget(paneA)
        self.img_vsplit.addWidget(paneB)
        self.img_vsplit.setStretchFactor(0, 1)
        self.img_vsplit.setStretchFactor(1, 1)
        self.img_vsplit.setSizes([420, 420])

        img_layout.addWidget(self.img_vsplit, 1)

        # Page navigation row
        nav_widget = QWidget()
        nav_flow = FlowLayout(nav_widget, margin=0, spacing=6)

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

        nav_flow.addWidget(self.btn_prev)
        nav_flow.addWidget(self.lbl_page)
        nav_flow.addWidget(self.btn_next)
        nav_flow.addWidget(self.btn_add_page)
        nav_flow.addWidget(self.btn_del_page)

        img_layout.addWidget(nav_widget)

        # ---------------- Notes panel (right): Description/Checklist + Ideas ----------------
        self.text_container = QWidget()
        text_layout = QVBoxLayout(self.text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        fmt_row = QWidget()
        fmt_outer = QVBoxLayout(fmt_row)
        fmt_outer.setContentsMargins(0, 0, 0, 0)
        fmt_outer.setSpacing(4)

        def _vsep() -> QFrame:
            v = QFrame()
            v.setFrameShape(QFrame.VLine)
            v.setFrameShadow(QFrame.Sunken)
            v.setStyleSheet("color: #CFCFCF;")
            v.setFixedHeight(22)
            return v

        self.btn_fmt_bold = QToolButton()
        self.btn_fmt_bold.setText("B")
        self.btn_fmt_bold.setCheckable(True)
        self.btn_fmt_bold.setFixedSize(28, 26)
        self.btn_fmt_bold.setToolTip("Bold (Ctrl+B)")
        self.btn_fmt_bold.setStyleSheet("font-weight: 800;")

        self.btn_fmt_italic = QToolButton()
        self.btn_fmt_italic.setText("I")
        self.btn_fmt_italic.setCheckable(True)
        self.btn_fmt_italic.setFixedSize(28, 26)
        self.btn_fmt_italic.setToolTip("Italic (Ctrl+I)")
        self.btn_fmt_italic.setStyleSheet("font-style: italic; font-weight: 600;")

        self.btn_fmt_underline = QToolButton()
        self.btn_fmt_underline.setText("U")
        self.btn_fmt_underline.setCheckable(True)
        self.btn_fmt_underline.setFixedSize(28, 26)
        self.btn_fmt_underline.setToolTip("Underline (Ctrl+U)")
        self.btn_fmt_underline.setStyleSheet("text-decoration: underline; font-weight: 600;")

        self.btn_fmt_bold.toggled.connect(lambda v: self._apply_format(bold=v))
        self.btn_fmt_italic.toggled.connect(lambda v: self._apply_format(italic=v))
        self.btn_fmt_underline.toggled.connect(lambda v: self._apply_format(underline=v))

        self._color_group = QButtonGroup(self)
        self._color_group.setExclusive(True)

        def _mk_color_btn(text: str, color_hex: str, tip: str) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setFixedSize(28, 26)
            b.setToolTip(tip)
            border = "1px solid #777" if color_hex.upper() == COLOR_YELLOW else "1px solid transparent"
            b.setStyleSheet(f"""
                QToolButton {{
                    background: {color_hex};
                    border: {border};
                    border-radius: 4px;
                    color: #111;
                    font-weight: 700;
                }}
                QToolButton:checked {{
                    border: 2px solid #111;
                }}
            """)
            return b

        self.btn_col_default = _mk_color_btn("A", COLOR_DEFAULT, "Text Color: Default")
        self.btn_col_red = _mk_color_btn("R", COLOR_RED, "Text Color: Red")
        self.btn_col_blue = _mk_color_btn("B", COLOR_BLUE, "Text Color: Blue")
        self.btn_col_yellow = _mk_color_btn("Y", COLOR_YELLOW, "Text Color: Yellow")

        self._color_group.addButton(self.btn_col_default, 0)
        self._color_group.addButton(self.btn_col_red, 1)
        self._color_group.addButton(self.btn_col_blue, 2)
        self._color_group.addButton(self.btn_col_yellow, 3)

        self.btn_col_default.toggled.connect(lambda v: v and self._apply_text_color(COLOR_DEFAULT))
        self.btn_col_red.toggled.connect(lambda v: v and self._apply_text_color(COLOR_RED))
        self.btn_col_blue.toggled.connect(lambda v: v and self._apply_text_color(COLOR_BLUE))
        self.btn_col_yellow.toggled.connect(lambda v: v and self._apply_text_color(COLOR_YELLOW))

        self.btn_bullets = QToolButton()
        self.btn_bullets.setText("•")
        self.btn_bullets.setFixedSize(28, 26)
        self.btn_bullets.setToolTip("Bulleted List")
        self.btn_bullets.clicked.connect(lambda: self._apply_list("bullet"))

        self.btn_numbered = QToolButton()
        self.btn_numbered.setText("1.")
        self.btn_numbered.setFixedSize(32, 26)
        self.btn_numbered.setToolTip("Numbered List")
        self.btn_numbered.clicked.connect(lambda: self._apply_list("number"))

        self.btn_ideas = QToolButton()
        self.btn_ideas.setText("Ideas")
        self.btn_ideas.setToolTip("Toggle Global Ideas panel (전역 아이디어)")
        self.btn_ideas.setCheckable(True)
        self.btn_ideas.toggled.connect(self._on_toggle_ideas)

        row1 = QWidget()
        r1 = QHBoxLayout(row1)
        r1.setContentsMargins(0, 0, 0, 0)
        r1.setSpacing(6)

        self.text_title = QLabel("Description / Notes")
        self.text_title.setStyleSheet("font-weight: 600;")

        r1.addWidget(self.text_title)
        r1.addWidget(_vsep())
        r1.addWidget(self.btn_fmt_bold)
        r1.addWidget(self.btn_fmt_italic)
        r1.addWidget(self.btn_fmt_underline)
        r1.addStretch(1)
        r1.addWidget(self.btn_ideas)

        row2 = QWidget()
        r2 = QHBoxLayout(row2)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(6)

        r2.addWidget(self.btn_col_default)
        r2.addWidget(self.btn_col_red)
        r2.addWidget(self.btn_col_blue)
        r2.addWidget(self.btn_col_yellow)
        r2.addWidget(_vsep())
        r2.addWidget(self.btn_bullets)
        r2.addWidget(self.btn_numbered)
        r2.addStretch(1)

        fmt_outer.addWidget(row1)
        fmt_outer.addWidget(row2)

        self.notes_ideas_splitter = QSplitter(Qt.Horizontal)
        self.notes_ideas_splitter.setChildrenCollapsible(False)

        self.notes_left = QWidget()
        notes_left_l = QVBoxLayout(self.notes_left)
        notes_left_l.setContentsMargins(0, 0, 0, 0)
        notes_left_l.setSpacing(6)

        self.chk_group = QGroupBox("Checklist")
        chk_layout = QVBoxLayout(self.chk_group)
        chk_layout.setContentsMargins(10, 10, 10, 10)
        chk_layout.setSpacing(6)

        self.chk_boxes: List[QCheckBox] = []
        self.chk_notes: List[QTextEdit] = []

        for q in DEFAULT_CHECK_QUESTIONS:
            cb = QCheckBox(q)
            cb.stateChanged.connect(self._on_page_field_changed)
            self.chk_boxes.append(cb)

            note = QTextEdit()
            note.setPlaceholderText("간단 설명을 입력하세요... (서식/색상 가능)")
            note.setFixedHeight(54)
            note.textChanged.connect(self._on_page_field_changed)
            note.installEventFilter(self)
            note.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
            note.setTabChangesFocus(False)
            self.chk_notes.append(note)

            chk_layout.addWidget(cb)
            chk_layout.addWidget(note)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("추가 분석/설명을 자유롭게 작성하세요... (서식/색상 가능)")
        self.text_edit.textChanged.connect(self._on_page_field_changed)
        self.text_edit.installEventFilter(self)
        self.text_edit.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
        self.text_edit.setTabChangesFocus(False)

        notes_left_l.addWidget(self.chk_group)
        notes_left_l.addWidget(self.text_edit, 1)

        self.ideas_panel = QFrame()
        self.ideas_panel.setFrameShape(QFrame.StyledPanel)
        self.ideas_panel.setMinimumWidth(320)
        self.ideas_panel.setStyleSheet("""
            QFrame {
                background: #FAFAFA;
                border: 1px solid #D0D0D0;
                border-radius: 10px;
            }
        """)

        ideas_l = QVBoxLayout(self.ideas_panel)
        ideas_l.setContentsMargins(10, 10, 10, 10)
        ideas_l.setSpacing(6)

        self.lbl_ideas = QLabel("Global Ideas")
        self.lbl_ideas.setStyleSheet("font-weight: 700;")
        ideas_l.addWidget(self.lbl_ideas)

        self.edit_global_ideas = QTextEdit()
        self.edit_global_ideas.setPlaceholderText("전역적으로 적용할 아이디어를 여기에 작성하세요... (서식/색상 가능)")
        self.edit_global_ideas.textChanged.connect(self._on_page_field_changed)
        self.edit_global_ideas.installEventFilter(self)
        self.edit_global_ideas.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
        self.edit_global_ideas.setTabChangesFocus(False)
        ideas_l.addWidget(self.edit_global_ideas, 1)

        self.notes_ideas_splitter.addWidget(self.notes_left)
        self.notes_ideas_splitter.addWidget(self.ideas_panel)
        self.notes_ideas_splitter.setStretchFactor(0, 3)
        self.notes_ideas_splitter.setStretchFactor(1, 1)

        text_layout.addWidget(fmt_row)
        text_layout.addWidget(self.notes_ideas_splitter, 1)

        # Assemble page_splitter (Charts left, Notes right)
        self.page_splitter.addWidget(self.img_panel)
        self.page_splitter.addWidget(self.text_container)
        self.page_splitter.setStretchFactor(0, 2)
        self.page_splitter.setStretchFactor(1, 1)

        main_content_l.addWidget(self.page_splitter, 1)

        # Trace panel (bottom inside right_vsplit)
        trace_container = QWidget()
        tc_l = QVBoxLayout(trace_container)
        tc_l.setContentsMargins(0, 0, 0, 0)
        tc_l.setSpacing(6)

        self.trace_group = QGroupBox("Trace")
        self.trace_group.setStyleSheet("QGroupBox { font-weight: 600; }")

        trace_l = QVBoxLayout(self.trace_group)
        trace_l.setContentsMargins(10, 10, 10, 10)
        trace_l.setSpacing(6)

        trace_bar = QWidget()
        trace_bar_l = QHBoxLayout(trace_bar)
        trace_bar_l.setContentsMargins(0, 0, 0, 0)
        trace_bar_l.setSpacing(6)

        self.btn_trace_clear = QPushButton("Clear")
        self.btn_trace_copy = QPushButton("Copy")
        self.btn_trace_hide = QPushButton("Hide")

        self.btn_trace_clear.clicked.connect(self._clear_trace)
        self.btn_trace_copy.clicked.connect(self._copy_trace_to_clipboard)
        self.btn_trace_hide.clicked.connect(lambda: self._set_trace_visible(False, persist=True))

        trace_bar_l.addWidget(QLabel("Debug output"), 1)
        trace_bar_l.addWidget(self.btn_trace_copy)
        trace_bar_l.addWidget(self.btn_trace_clear)
        trace_bar_l.addWidget(self.btn_trace_hide)

        self.trace_edit = QPlainTextEdit()
        self.trace_edit.setReadOnly(True)
        self.trace_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.trace_edit.setStyleSheet("""
            QPlainTextEdit {
                background: #0F1115;
                color: #D7D7D7;
                border: 1px solid #2A2F3A;
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
            }
        """)

        trace_l.addWidget(trace_bar)
        trace_l.addWidget(self.trace_edit, 1)

        self.trace_show_row = QWidget()
        tsr_l = QHBoxLayout(self.trace_show_row)
        tsr_l.setContentsMargins(0, 0, 0, 0)
        tsr_l.setSpacing(6)
        self.btn_trace_show = QPushButton("Show Trace")
        self.btn_trace_show.clicked.connect(lambda: self._set_trace_visible(True, persist=True))
        tsr_l.addStretch(1)
        tsr_l.addWidget(self.btn_trace_show)

        tc_l.addWidget(self.trace_group, 1)
        tc_l.addWidget(self.trace_show_row, 0)

        self.right_vsplit.addWidget(main_content)
        self.right_vsplit.addWidget(trace_container)
        self.right_vsplit.setStretchFactor(0, 1)
        self.right_vsplit.setStretchFactor(1, 0)
        self.right_vsplit.setSizes([760, 210])

        right_layout.addWidget(self.right_vsplit, 1)

        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([360, 1100])

        layout.addWidget(self.main_splitter, 1)

        self.text_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.img_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.text_container.setMinimumWidth(440)

        self._set_active_rich_edit(self.text_edit)
        self.btn_col_default.setChecked(True)

    # ---------------- overlays for pane A/B ----------------
    def _build_pane_overlays(self) -> None:
        self._pane_ui = {}
        self._pane_ui["A"] = self._build_overlay_for_pane("A", self.viewer_a)
        self._pane_ui["B"] = self._build_overlay_for_pane("B", self.viewer_b)
        self._set_active_pane("A")

    def _build_overlay_for_pane(self, pane: str, viewer: Optional[ZoomPanAnnotateView]) -> Dict[str, Any]:
        if viewer is None:
            return {}

        vp = viewer.viewport()

        edit_cap = CollapsibleCaptionEdit(vp, collapsed_h=28, expanded_h=84)
        edit_cap.setPlaceholderTextCompat(f"{pane} 이미지 간단 설명 (hover/클릭 시 2~3줄 확장)")
        edit_cap.textChanged.connect(self._on_page_field_changed)
        edit_cap.expandedChanged.connect(lambda _: self._reposition_overlay(pane))

        btn_anno_toggle = QToolButton(vp)
        btn_anno_toggle.setText("✎")
        btn_anno_toggle.setToolTip(f"Open Annotate panel ({pane})")
        btn_anno_toggle.setAutoRaise(True)
        btn_anno_toggle.setFixedSize(34, 30)

        btn_desc_toggle = QToolButton(vp)
        btn_desc_toggle.setText("Notes✓" if self._desc_visible else "Notes")
        btn_desc_toggle.setToolTip("Show/Hide Description & Checklist panel")
        btn_desc_toggle.setCheckable(True)
        btn_desc_toggle.setChecked(bool(self._desc_visible))
        btn_desc_toggle.setAutoRaise(True)
        btn_desc_toggle.setFixedSize(64, 30)
        btn_desc_toggle.toggled.connect(self._on_toggle_desc)

        anno_panel = QFrame(vp)
        anno_panel.setFrameShape(QFrame.StyledPanel)
        anno_panel.setVisible(False)
        anno_panel.setFixedWidth(240)
        anno_panel.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 235);
                border: 1px solid #9A9A9A;
                border-radius: 10px;
            }
            QLabel { color: #222; }
        """)

        p_layout = QVBoxLayout(anno_panel)
        p_layout.setContentsMargins(10, 10, 10, 10)
        p_layout.setSpacing(8)

        header = QWidget(anno_panel)
        header_l = QHBoxLayout(header)
        header_l.setContentsMargins(0, 0, 0, 0)
        header_l.setSpacing(6)

        lbl = QLabel(f"Annotate ({pane})", header)
        lbl.setStyleSheet("font-weight: 600;")
        header_l.addWidget(lbl, 1)

        btn_anno_close = QToolButton(header)
        btn_anno_close.setText("×")
        btn_anno_close.setToolTip("Close panel")
        btn_anno_close.setAutoRaise(True)
        btn_anno_close.setFixedSize(26, 22)
        header_l.addWidget(btn_anno_close)

        p_layout.addWidget(header)

        btn_draw_mode = QToolButton(anno_panel)
        btn_draw_mode.setText("Draw")
        btn_draw_mode.setCheckable(True)
        btn_draw_mode.setToolTip("Toggle draw mode. Drag to draw. Hold SHIFT for straight line.")
        p_layout.addWidget(btn_draw_mode)

        color_row = QWidget(anno_panel)
        color_l = QHBoxLayout(color_row)
        color_l.setContentsMargins(0, 0, 0, 0)
        color_l.setSpacing(6)
        color_l.addWidget(QLabel("Color"))
        combo_color = QComboBox(color_row)
        combo_color.addItem("Red", COLOR_RED)
        combo_color.addItem("Yellow", COLOR_YELLOW)
        combo_color.addItem("Cyan", "#00D5FF")
        combo_color.addItem("White", "#FFFFFF")
        color_l.addWidget(combo_color, 1)
        p_layout.addWidget(color_row)

        width_row = QWidget(anno_panel)
        width_l = QHBoxLayout(width_row)
        width_l.setContentsMargins(0, 0, 0, 0)
        width_l.setSpacing(6)
        width_l.addWidget(QLabel("Width"))
        combo_width = QComboBox(width_row)
        for w in ["2", "3", "4", "6", "8"]:
            combo_width.addItem(f"{w}px", float(w))
        combo_width.setCurrentIndex(1)
        width_l.addWidget(combo_width, 1)
        p_layout.addWidget(width_row)

        btn_clear_lines = QPushButton("Clear Lines", anno_panel)
        p_layout.addWidget(btn_clear_lines)

        def apply_pen():
            viewer.set_pen(str(combo_color.currentData()), float(combo_width.currentData()))

        combo_color.currentIndexChanged.connect(lambda _: apply_pen())
        combo_width.currentIndexChanged.connect(lambda _: apply_pen())
        apply_pen()

        def toggle_draw(checked: bool):
            self._set_active_pane(pane)
            if checked:
                viewer.set_mode_draw()
            else:
                viewer.set_mode_pan()
            viewer.setFocus(Qt.MouseFocusReason)
            self.trace(f"Pane {pane} draw_mode={'ON' if checked else 'OFF'}", "DEBUG")

        btn_draw_mode.toggled.connect(toggle_draw)

        def clear_lines():
            self._set_active_pane(pane)
            pg = self.current_page()
            if not pg:
                return
            if not viewer.get_strokes():
                return
            reply = QMessageBox.question(
                self,
                "Clear Lines",
                f"Clear all annotation lines on Chart {pane}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            viewer.clear_strokes()
            self._flush_page_fields_to_model_and_save()
            viewer.setFocus(Qt.MouseFocusReason)
            self.trace(f"Cleared strokes on pane {pane}", "INFO")

        btn_clear_lines.clicked.connect(clear_lines)

        def open_panel():
            self._set_active_pane(pane)
            btn_anno_toggle.setVisible(False)
            anno_panel.setVisible(True)
            self._reposition_overlay(pane)
            self.trace(f"Opened annotate panel ({pane})", "DEBUG")

        def close_panel():
            if btn_draw_mode.isChecked():
                btn_draw_mode.setChecked(False)
                viewer.set_mode_pan()
            anno_panel.setVisible(False)
            btn_anno_toggle.setVisible(True)
            self._reposition_overlay(pane)
            self.trace(f"Closed annotate panel ({pane})", "DEBUG")

        btn_anno_toggle.clicked.connect(open_panel)
        btn_anno_close.clicked.connect(close_panel)

        self._reposition_overlay(pane)

        return {
            "viewer": viewer,
            "cap": edit_cap,
            "anno_toggle": btn_anno_toggle,
            "desc_toggle": btn_desc_toggle,
            "panel": anno_panel,
            "draw": btn_draw_mode,
            "close": btn_anno_close,
        }

    def _set_active_pane(self, pane: str) -> None:
        if pane not in ("A", "B"):
            pane = "A"
        self._active_pane = pane
        if self.viewer_a is not None:
            self.viewer_a.setStyleSheet("border: 2px solid #5A8DFF;" if pane == "A" else "border: 1px solid #D0D0D0;")
        if self.viewer_b is not None:
            self.viewer_b.setStyleSheet("border: 2px solid #5A8DFF;" if pane == "B" else "border: 1px solid #D0D0D0;")

    def _reposition_overlay(self, pane: str) -> None:
        ui = self._pane_ui.get(pane, {})
        viewer: Optional[ZoomPanAnnotateView] = ui.get("viewer")
        if viewer is None:
            return
        vp = viewer.viewport()

        edit_cap: CollapsibleCaptionEdit = ui["cap"]
        btn_anno_toggle: QToolButton = ui["anno_toggle"]
        btn_desc_toggle: QToolButton = ui["desc_toggle"]
        anno_panel: QFrame = ui["panel"]

        w = vp.width()
        margin = 10
        gap = 6

        if anno_panel.isVisible():
            panel_x = max(margin, w - anno_panel.width() - margin)
            anno_panel.move(panel_x, margin)
            btn_desc_toggle.move(max(margin, panel_x - margin - btn_desc_toggle.width()), margin)
        else:
            btn_anno_toggle.move(max(margin, w - btn_anno_toggle.width() - margin), margin)
            btn_desc_toggle.move(max(margin, w - btn_desc_toggle.width() - margin), margin + btn_anno_toggle.height() + gap)

        cap_min = 260
        cap_max = 720
        if anno_panel.isVisible():
            cap_right_limit = anno_panel.x() - margin
        else:
            cap_right_limit = min(btn_anno_toggle.x(), btn_desc_toggle.x()) - margin

        cap_w = min(cap_max, max(cap_min, cap_right_limit - margin))
        cap_x = max(margin, cap_right_limit - cap_w)
        edit_cap.setFixedWidth(cap_w)
        edit_cap.move(cap_x, margin)

    # ---------------- Splitter persistence ----------------
    def _is_valid_splitter_sizes(self, v: Any) -> bool:
        return (
            isinstance(v, list)
            and len(v) == 2
            and all(isinstance(x, int) for x in v)
            and v[0] >= 0 and v[1] >= 0
        )

    def _apply_splitter_sizes_from_state(self) -> None:
        self._loading_ui = True
        try:
            ms = self.db.ui_state.get("main_splitter_sizes")
            if self._is_valid_splitter_sizes(ms):
                try:
                    self.main_splitter.setSizes(ms)
                except Exception:
                    pass

            ps = self.db.ui_state.get("page_splitter_sizes")
            if self._is_valid_splitter_sizes(ps):
                try:
                    self.page_splitter.setSizes(ps)
                except Exception:
                    pass

            ns = self.db.ui_state.get("notes_splitter_sizes")
            if self._is_valid_splitter_sizes(ns):
                try:
                    self.notes_ideas_splitter.setSizes(ns)
                except Exception:
                    pass

            vs = self.db.ui_state.get("img_vsplit_sizes")
            if self._is_valid_splitter_sizes(vs):
                try:
                    self.img_vsplit.setSizes(vs)
                except Exception:
                    pass

            rvs = self.db.ui_state.get("right_vsplit_sizes")
            if self._is_valid_splitter_sizes(rvs):
                try:
                    self.right_vsplit.setSizes(rvs)
                except Exception:
                    pass
        finally:
            self._loading_ui = False

    def _remember_splitter_sizes(self) -> None:
        try:
            ms = self.main_splitter.sizes()
            if self._is_valid_splitter_sizes(ms):
                self.db.ui_state["main_splitter_sizes"] = [int(ms[0]), int(ms[1])]
        except Exception:
            pass
        try:
            ps = self.page_splitter.sizes()
            if self._is_valid_splitter_sizes(ps):
                self.db.ui_state["page_splitter_sizes"] = [int(ps[0]), int(ps[1])]
        except Exception:
            pass
        try:
            ns = self.notes_ideas_splitter.sizes()
            if self._is_valid_splitter_sizes(ns):
                self.db.ui_state["notes_splitter_sizes"] = [int(ns[0]), int(ns[1])]
        except Exception:
            pass
        try:
            vs = self.img_vsplit.sizes()
            if self._is_valid_splitter_sizes(vs):
                self.db.ui_state["img_vsplit_sizes"] = [int(vs[0]), int(vs[1])]
        except Exception:
            pass
        try:
            rvs = self.right_vsplit.sizes()
            if self._is_valid_splitter_sizes(rvs):
                self.db.ui_state["right_vsplit_sizes"] = [int(rvs[0]), int(rvs[1])]
        except Exception:
            pass

    def _post_init_layout_fix(self) -> None:
        try:
            self._apply_splitter_sizes_from_state()
            self._update_text_area_layout()
            for pane in ("A", "B"):
                self._reposition_overlay(pane)
            self.trace("Post-init layout fix applied", "DEBUG")
        except Exception as e:
            self.trace(f"Post-init layout fix failed: {e}", "WARN")

    def closeEvent(self, event) -> None:
        try:
            self._flush_page_fields_to_model_and_save()
            self._save_ui_state()
            self._remember_splitter_sizes()
            self.db.save()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- Tree build/refresh ----------------
    def _refresh_tree(self, select_current: bool = False) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        def add_cat(parent_item: Optional[QTreeWidgetItem], cat: Category) -> QTreeWidgetItem:
            it = QTreeWidgetItem([cat.name])
            it.setData(0, self.NODE_TYPE_ROLE, "category")
            it.setData(0, self.CATEGORY_ID_ROLE, cat.id)
            flags = it.flags()
            flags |= Qt.ItemIsSelectable | Qt.ItemIsEnabled
            it.setFlags(flags)
            if parent_item is None:
                self.tree.addTopLevelItem(it)
            else:
                parent_item.addChild(it)

            # children categories first
            for sub in cat.categories:
                add_cat(it, sub)
            # then items
            for item in cat.items:
                child = QTreeWidgetItem([item.name])
                child.setData(0, self.NODE_TYPE_ROLE, "item")
                child.setData(0, self.ITEM_ID_ROLE, item.id)
                flags2 = child.flags()
                flags2 |= Qt.ItemIsSelectable | Qt.ItemIsEnabled
                child.setFlags(flags2)
                it.addChild(child)

            it.setExpanded(True)
            return it

        # render root categories as top-level folders
        selected_qitem: Optional[QTreeWidgetItem] = None
        for c in self.db.root.categories:
            top = add_cat(None, c)
            if select_current and self.current_category_id and c.id == self.current_category_id:
                selected_qitem = top

        # If current item exists, prefer selecting the item
        if select_current and self.current_item_id:
            item_q = self._find_tree_item_by_item_id(self.current_item_id)
            if item_q is not None:
                selected_qitem = item_q

        if selected_qitem is not None:
            self.tree.setCurrentItem(selected_qitem)

        self.tree.blockSignals(False)

    def _find_tree_item_by_item_id(self, item_id: str) -> Optional[QTreeWidgetItem]:
        def walk(q: QTreeWidgetItem) -> Optional[QTreeWidgetItem]:
            ntype = q.data(0, self.NODE_TYPE_ROLE)
            if ntype == "item" and str(q.data(0, self.ITEM_ID_ROLE) or "") == item_id:
                return q
            for i in range(q.childCount()):
                r = walk(q.child(i))
                if r is not None:
                    return r
            return None

        for i in range(self.tree.topLevelItemCount()):
            r = walk(self.tree.topLevelItem(i))
            if r is not None:
                return r
        return None

    def _on_tree_selection_changed(self) -> None:
        item = self.tree.currentItem()
        if not item:
            return

        node_type = item.data(0, self.NODE_TYPE_ROLE)
        if node_type == "category":
            cid = str(item.data(0, self.CATEGORY_ID_ROLE) or "")
            if cid and cid != self.current_category_id:
                self._flush_page_fields_to_model_and_save()
                self.current_category_id = cid
                # selecting category does not imply selecting item
                self.current_item_id = ""
                self.current_page_index = 0
                self._save_ui_state()
                self._load_current_item_page_to_ui(clear_only=True)
                self.trace(f"Selected folder: {item.text(0)}", "INFO")
            return

        if node_type == "item":
            iid = str(item.data(0, self.ITEM_ID_ROLE) or "")
            if not iid or iid == self.current_item_id:
                return

            self._flush_page_fields_to_model_and_save()
            found = self.db.find_item(iid)
            if not found:
                return
            it, parent = found
            self.current_item_id = it.id
            self.current_category_id = parent.id
            self.current_page_index = max(0, min(it.last_page_index, len(it.pages) - 1))
            self._save_ui_state()
            self._load_current_item_page_to_ui()
            self.trace(f"Selected item: {it.name}", "INFO")

    # ---------------- Context menu ----------------
    def _on_tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        node_type = item.data(0, self.NODE_TYPE_ROLE)

        menu = QMenu(self)
        act_add_folder = menu.addAction("+ Folder")
        act_add_item = menu.addAction("+ Item")
        menu.addSeparator()
        act_rename = menu.addAction("Rename")
        act_delete = menu.addAction("Delete")
        menu.addSeparator()
        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")

        if node_type == "category":
            # ok
            pass
        elif node_type == "item":
            # ok
            pass
        else:
            return

        chosen = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if not chosen:
            return
        if chosen == act_add_folder:
            self.add_folder()
        elif chosen == act_add_item:
            self.add_item()
        elif chosen == act_rename:
            self.rename_node()
        elif chosen == act_delete:
            self.delete_node()
        elif chosen == act_up:
            self.move_node(-1)
        elif chosen == act_down:
            self.move_node(+1)

    # ---------------- Node operations ----------------
    def _effective_selected_category_id(self) -> str:
        """
        Category selected: itself
        Item selected: its parent category
        None: root
        """
        cur = self.tree.currentItem()
        if cur:
            ntype = cur.data(0, self.NODE_TYPE_ROLE)
            if ntype == "category":
                cid = str(cur.data(0, self.CATEGORY_ID_ROLE) or "")
                if cid:
                    return cid
            if ntype == "item":
                iid = str(cur.data(0, self.ITEM_ID_ROLE) or "")
                found = self.db.find_item(iid)
                if found:
                    _, parent = found
                    return parent.id
        if self.current_category_id:
            return self.current_category_id
        return ROOT_CATEGORY_ID

    def add_folder(self) -> None:
        parent_id = self._effective_selected_category_id()
        base_name = "New Folder"
        name, ok = QInputDialog.getText(self, "Add Folder", "Folder name:", text=base_name)
        if not ok or not name.strip():
            return
        self._flush_page_fields_to_model_and_save()
        new_cat = self.db.add_category(parent_id, name.strip())
        self.current_category_id = new_cat.id
        self.current_item_id = ""
        self.current_page_index = 0
        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_tree(select_current=True)
        self.trace(f"Added folder '{new_cat.name}' under parent={parent_id}", "INFO")

    def add_item(self) -> None:
        parent_id = self._effective_selected_category_id()
        name, ok = QInputDialog.getText(self, "Add Item", "Item name:", text="New Item")
        if not ok or not name.strip():
            return
        self._flush_page_fields_to_model_and_save()
        it = self.db.add_item(parent_id, name.strip())
        self.current_item_id = it.id
        self.current_category_id = parent_id if parent_id != ROOT_CATEGORY_ID else ""
        self.current_page_index = 0
        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_tree(select_current=True)
        self._load_current_item_page_to_ui()
        self.trace(f"Added item '{it.name}' under category={parent_id}", "INFO")

    def rename_node(self) -> None:
        cur = self.tree.currentItem()
        if not cur:
            return
        ntype = cur.data(0, self.NODE_TYPE_ROLE)
        if ntype == "category":
            cid = str(cur.data(0, self.CATEGORY_ID_ROLE) or "")
            cat = self.db.find_category(cid)
            if not cat or cid == ROOT_CATEGORY_ID:
                return
            new_name, ok = QInputDialog.getText(self, "Rename Folder", "New name:", text=cat.name)
            if not ok or not new_name.strip():
                return
            self._flush_page_fields_to_model_and_save()
            old = cat.name
            cat.name = new_name.strip()
            cat.updated_at = _now_epoch()
            self._save_db_with_warning()
            self._refresh_tree(select_current=True)
            self.trace(f"Renamed folder '{old}' -> '{cat.name}'", "INFO")
            return

        if ntype == "item":
            iid = str(cur.data(0, self.ITEM_ID_ROLE) or "")
            found = self.db.find_item(iid)
            if not found:
                return
            it, _ = found
            new_name, ok = QInputDialog.getText(self, "Rename Item", "New name:", text=it.name)
            if not ok or not new_name.strip():
                return
            self._flush_page_fields_to_model_and_save()
            old = it.name
            it.name = new_name.strip()
            it.updated_at = _now_epoch()
            self._save_db_with_warning()
            self._refresh_tree(select_current=True)
            self.trace(f"Renamed item '{old}' -> '{it.name}'", "INFO")

    def delete_node(self) -> None:
        cur = self.tree.currentItem()
        if not cur:
            return
        ntype = cur.data(0, self.NODE_TYPE_ROLE)

        if ntype == "category":
            cid = str(cur.data(0, self.CATEGORY_ID_ROLE) or "")
            if not cid or cid == ROOT_CATEGORY_ID:
                return
            cat = self.db.find_category(cid)
            if not cat:
                return

            # confirm (recursive)
            has_children = bool(cat.categories) or bool(cat.items)
            msg = f"Delete folder '{cat.name}'?"
            if has_children:
                msg += "\n\nThis folder contains subfolders/items.\nDeleting will remove everything under it."
            reply = QMessageBox.question(
                self,
                "Delete Folder",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            self._flush_page_fields_to_model_and_save()
            ok = self.db.delete_category_recursive(cid)
            if not ok:
                return

            # fix selection
            if self.current_category_id == cid:
                self.current_category_id = ""
            if self.current_item_id and self.db.find_item(self.current_item_id) is None:
                self.current_item_id = ""

            self._ensure_valid_selection()
            self._save_ui_state()
            self._save_db_with_warning()
            self._refresh_tree(select_current=True)
            self._load_current_item_page_to_ui()
            self.trace(f"Deleted folder '{cat.name}'", "WARN")
            return

        if ntype == "item":
            iid = str(cur.data(0, self.ITEM_ID_ROLE) or "")
            found = self.db.find_item(iid)
            if not found:
                return
            it, _ = found

            reply = QMessageBox.question(
                self,
                "Delete Item",
                f"Delete item '{it.name}' and all its pages?\n(This cannot be undone.)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            # prevent deleting last remaining item
            # Count all items
            if self._count_items(self.db.root) <= 1:
                QMessageBox.warning(self, "Not allowed", "At least one item must remain.")
                return

            self._flush_page_fields_to_model_and_save()
            self.db.delete_item(iid)

            if self.current_item_id == iid:
                self.current_item_id = ""
            self._ensure_valid_selection()
            self._save_ui_state()
            self._save_db_with_warning()
            self._refresh_tree(select_current=True)
            self._load_current_item_page_to_ui()
            self.trace(f"Deleted item '{it.name}'", "WARN")

    def _count_items(self, cat: Category) -> int:
        n = len(cat.items)
        for c in cat.categories:
            n += self._count_items(c)
        return n

    def move_node(self, direction: int) -> None:
        cur = self.tree.currentItem()
        if not cur:
            return
        ntype = cur.data(0, self.NODE_TYPE_ROLE)

        self._flush_page_fields_to_model_and_save()

        if ntype == "category":
            cid = str(cur.data(0, self.CATEGORY_ID_ROLE) or "")
            if not cid or cid == ROOT_CATEGORY_ID:
                return
            ok = self.db.move_category(cid, direction)
            if ok:
                self._save_db_with_warning()
                self._refresh_tree(select_current=True)
                self.trace(f"Moved folder (dir={direction})", "DEBUG")
            return

        if ntype == "item":
            iid = str(cur.data(0, self.ITEM_ID_ROLE) or "")
            if not iid:
                return
            ok = self.db.move_item(iid, direction)
            if ok:
                self._save_db_with_warning()
                self._refresh_tree(select_current=True)
                self.trace(f"Moved item (dir={direction})", "DEBUG")

    # ---------------- Current item/page access ----------------
    def current_item(self) -> Optional[Item]:
        found = self.db.find_item(self.current_item_id)
        if not found:
            return None
        it, _ = found
        return it

    def current_page(self) -> Optional[Page]:
        it = self.current_item()
        if not it or not it.pages:
            return None
        idx = max(0, min(self.current_page_index, len(it.pages) - 1))
        return it.pages[idx]

    # ---------------- Save ui state ----------------
    def _save_ui_state(self) -> None:
        self.db.ui_state["selected_category_id"] = self.current_category_id
        self.db.ui_state["selected_item_id"] = self.current_item_id
        self.db.ui_state["current_page_index"] = int(self.current_page_index)
        self.db.ui_state["desc_visible"] = bool(self._desc_visible)
        self.db.ui_state["global_ideas_visible"] = bool(self.ideas_panel.isVisible())
        self.db.ui_state["trace_visible"] = bool(self._trace_visible)

    # ---------------- Safe save wrapper ----------------
    def _save_db_with_warning(self) -> bool:
        ok = self.db.save()
        if ok:
            return True

        now = time.time()
        if (now - self._last_save_warn_ts) >= self._save_warn_cooldown_sec:
            self._last_save_warn_ts = now
            self.trace("Save failed (possible file lock). autosave may have been created.", "WARN")
            QMessageBox.warning(
                self,
                "Save warning",
                "JSON 저장에 실패했습니다(파일이 다른 프로그램에 의해 잠겼을 수 있습니다).\n\n"
                "조치:\n"
                "- VS Code에서 data/notes_db.json 탭을 닫거나 JSON Viewer/Preview 확장이 파일을 잡고 있지 않은지 확인\n"
                "- 앱이 2개 실행 중인지 확인\n"
                "- OneDrive/백신 실시간 감시가 잠깐 락을 거는 경우 잠시 후 자동 저장 재시도\n\n"
                "데이터 보호:\n"
                "- data 폴더에 notes_db.json.autosave.<timestamp>.json 파일이 생성되었을 수 있습니다."
            )
        return False

    # ---------------- Page load/save ----------------
    def _load_current_item_page_to_ui(self, clear_only: bool = False) -> None:
        it = self.current_item()
        pg = self.current_page()

        if clear_only or not it or not pg:
            self._loading_ui = True
            try:
                self.edit_stock_name.clear()
                self.edit_ticker.clear()

                for pane in ("A", "B"):
                    ui = self._pane_ui.get(pane, {})
                    if ui:
                        ui["cap"].setPlainText("")
                        ui["draw"].setChecked(False)
                        ui["panel"].setVisible(False)
                        ui["anno_toggle"].setVisible(True)
                    viewer = self.viewer_a if pane == "A" else self.viewer_b
                    if viewer is not None:
                        viewer.clear_image()

                for cb in self.chk_boxes:
                    cb.setChecked(False)
                for note in self.chk_notes:
                    note.clear()
                self.text_edit.clear()
                self._update_nav(0, 0)
            finally:
                self._loading_ui = False
            return

        self._loading_ui = True
        try:
            # clamp page index
            self.current_page_index = max(0, min(self.current_page_index, len(it.pages) - 1))
            pg = it.pages[self.current_page_index]

            self.edit_stock_name.setText(pg.stock_name or "")
            self.edit_ticker.setText(pg.ticker or "")

            if self._pane_ui.get("A"):
                self._pane_ui["A"]["cap"].setPlainText(pg.image_a_caption or "")
            if self._pane_ui.get("B"):
                self._pane_ui["B"]["cap"].setPlainText(pg.image_b_caption or "")

            if self.viewer_a is not None:
                if pg.image_a_path and os.path.exists(_abspath_from_rel(pg.image_a_path)):
                    self.viewer_a.set_image_path(_abspath_from_rel(pg.image_a_path))
                else:
                    self.viewer_a.clear_image()
                self.viewer_a.set_strokes(pg.strokes_a or [])
                self.viewer_a.set_mode_pan()

            if self.viewer_b is not None:
                if pg.image_b_path and os.path.exists(_abspath_from_rel(pg.image_b_path)):
                    self.viewer_b.set_image_path(_abspath_from_rel(pg.image_b_path))
                else:
                    self.viewer_b.clear_image()
                self.viewer_b.set_strokes(pg.strokes_b or [])
                self.viewer_b.set_mode_pan()

            cl = _normalize_checklist(pg.checklist)
            for i in range(len(DEFAULT_CHECK_QUESTIONS)):
                self.chk_boxes[i].setChecked(bool(cl[i].get("checked", False)))
                val = _strip_highlight_html(str(cl[i].get("note", "") or ""))
                if _looks_like_html(val):
                    self.chk_notes[i].setHtml(val)
                else:
                    self.chk_notes[i].setPlainText(val)

            val_desc = _strip_highlight_html(pg.note_text or "")
            if _looks_like_html(val_desc):
                self.text_edit.setHtml(val_desc)
            else:
                self.text_edit.setPlainText(val_desc)

            for pane in ("A", "B"):
                ui = self._pane_ui.get(pane, {})
                if ui:
                    ui["draw"].setChecked(False)
                    ui["panel"].setVisible(False)
                    ui["anno_toggle"].setVisible(True)
                    self._reposition_overlay(pane)

            self._update_nav(self.current_page_index + 1, len(it.pages))
            self._set_active_rich_edit(self.text_edit)
            self._sync_format_buttons()
        finally:
            self._loading_ui = False

        self.trace(f"Loaded page {self.current_page_index + 1}/{len(it.pages)} for item '{it.name}'", "DEBUG")

    def _on_page_field_changed(self) -> None:
        if self._loading_ui:
            return
        # no item selected => ignore
        if not self.current_item_id:
            return
        self._save_timer.start(450)

    def _collect_checklist_from_ui(self) -> Checklist:
        out: Checklist = []
        for i, q in enumerate(DEFAULT_CHECK_QUESTIONS):
            out.append(
                {
                    "q": q,
                    "checked": bool(self.chk_boxes[i].isChecked()),
                    "note": _strip_highlight_html(self.chk_notes[i].toHtml()),
                }
            )
        return out

    def _flush_page_fields_to_model_and_save(self) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg or self._loading_ui:
            # still save global ideas / ui state
            self._save_ui_state()
            self._remember_splitter_sizes()
            self._save_db_with_warning()
            return

        changed = False

        new_global = _strip_highlight_html(self.edit_global_ideas.toHtml())
        if self.db.global_ideas != new_global:
            self.db.global_ideas = new_global
            changed = True

        capA = self._pane_ui.get("A", {}).get("cap")
        capB = self._pane_ui.get("B", {}).get("cap")
        new_cap_a = capA.toPlainText() if capA is not None else ""
        new_cap_b = capB.toPlainText() if capB is not None else ""
        if pg.image_a_caption != new_cap_a:
            pg.image_a_caption = new_cap_a
            changed = True
        if pg.image_b_caption != new_cap_b:
            pg.image_b_caption = new_cap_b
            changed = True

        new_text = _strip_highlight_html(self.text_edit.toHtml())
        if pg.note_text != new_text:
            pg.note_text = new_text
            changed = True

        new_name = self.edit_stock_name.text()
        if pg.stock_name != new_name:
            pg.stock_name = new_name
            changed = True

        new_ticker = self.edit_ticker.text()
        if pg.ticker != new_ticker:
            pg.ticker = new_ticker
            changed = True

        if self.viewer_a is not None:
            new_strokes_a = self.viewer_a.get_strokes()
            if pg.strokes_a != new_strokes_a:
                pg.strokes_a = new_strokes_a
                changed = True

        if self.viewer_b is not None:
            new_strokes_b = self.viewer_b.get_strokes()
            if pg.strokes_b != new_strokes_b:
                pg.strokes_b = new_strokes_b
                changed = True

        new_checklist = self._collect_checklist_from_ui()
        if pg.checklist != new_checklist:
            pg.checklist = new_checklist
            changed = True

        it.last_page_index = self.current_page_index
        it.updated_at = _now_epoch()
        self._save_ui_state()
        self._remember_splitter_sizes()

        if changed:
            pg.updated_at = _now_epoch()
            self.trace(f"Auto-saved changes (item='{it.name}', page={self.current_page_index + 1})", "DEBUG")

        self._save_db_with_warning()

    def force_save(self) -> None:
        self._flush_page_fields_to_model_and_save()
        self.trace("Force save requested", "INFO")
        QMessageBox.information(self, "Saved", "Save requested (check warnings if file is locked).")

    def _update_nav(self, cur: int, total: int) -> None:
        self.lbl_page.setText(f"{cur} / {total}")
        self.btn_prev.setEnabled(total > 0 and self.current_page_index > 0)
        self.btn_next.setEnabled(total > 0 and self.current_page_index < total - 1)
        self.btn_del_page.setEnabled(total > 1)

    def _load_global_ideas_to_ui(self) -> None:
        self._loading_ui = True
        try:
            val = _strip_highlight_html(self.db.global_ideas or "")
            if _looks_like_html(val):
                self.edit_global_ideas.setHtml(val)
            else:
                self.edit_global_ideas.setPlainText(val)
        finally:
            self._loading_ui = False

    # ---------------- Page navigation ----------------
    def go_prev_page(self) -> None:
        it = self.current_item()
        if not it or self.current_page_index <= 0:
            return
        self._flush_page_fields_to_model_and_save()
        self.current_page_index -= 1
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._load_current_item_page_to_ui()
        self.trace("Prev page", "INFO")

    def go_next_page(self) -> None:
        it = self.current_item()
        if not it or self.current_page_index >= len(it.pages) - 1:
            return
        self._flush_page_fields_to_model_and_save()
        self.current_page_index += 1
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._load_current_item_page_to_ui()
        self.trace("Next page", "INFO")

    def add_page(self) -> None:
        it = self.current_item()
        if not it:
            return
        self._flush_page_fields_to_model_and_save()

        insert_at = self.current_page_index + 1
        it.pages.insert(insert_at, self.db.new_page())
        self.current_page_index = insert_at
        it.last_page_index = self.current_page_index
        it.updated_at = _now_epoch()

        self._save_ui_state()
        self._save_db_with_warning()
        self._load_current_item_page_to_ui()
        self.trace(f"Added page (now {self.current_page_index + 1}/{len(it.pages)})", "INFO")

    def delete_page(self) -> None:
        it = self.current_item()
        if not it or len(it.pages) <= 1:
            return

        reply = QMessageBox.question(
            self,
            "Delete Page",
            "Delete current page?\n(This cannot be undone.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._flush_page_fields_to_model_and_save()
        del it.pages[self.current_page_index]
        self.current_page_index = max(0, min(self.current_page_index, len(it.pages) - 1))
        it.last_page_index = self.current_page_index
        it.updated_at = _now_epoch()

        self._save_ui_state()
        self._save_db_with_warning()
        self._load_current_item_page_to_ui()
        self.trace(f"Deleted page (now {self.current_page_index + 1}/{len(it.pages)})", "WARN")

    # ---------------- Image handling (dual panes) ----------------
    def reset_image_view(self, pane: str) -> None:
        viewer = self.viewer_a if pane == "A" else self.viewer_b
        if viewer is None:
            return
        self._set_active_pane(pane)
        viewer.fit_to_view()
        viewer.setFocus(Qt.MouseFocusReason)
        self.trace(f"Fit view pane {pane}", "DEBUG")

    def _on_image_dropped(self, pane: str, path: str) -> None:
        self._set_image_from_file(pane, path)

    def set_image_via_dialog(self, pane: str) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select Chart Image ({pane})",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*.*)",
        )
        if not file_path:
            return
        self._set_image_from_file(pane, file_path)

    def clear_image(self, pane: str) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg:
            return

        viewer = self.viewer_a if pane == "A" else self.viewer_b
        if viewer is None:
            return

        self._set_active_pane(pane)
        self._flush_page_fields_to_model_and_save()

        if pane == "A":
            pg.image_a_path = ""
            pg.strokes_a = []
            pg.image_a_caption = ""
            if self._pane_ui.get("A"):
                self._pane_ui["A"]["cap"].setPlainText("")
        else:
            pg.image_b_path = ""
            pg.strokes_b = []
            pg.image_b_caption = ""
            if self._pane_ui.get("B"):
                self._pane_ui["B"]["cap"].setPlainText("")

        pg.updated_at = _now_epoch()
        it.updated_at = _now_epoch()
        self._save_db_with_warning()
        viewer.clear_image()
        self.trace(f"Cleared image pane {pane}", "INFO")

    def paste_image_from_clipboard(self, pane: str) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg:
            return

        viewer = self.viewer_a if pane == "A" else self.viewer_b
        if viewer is None:
            return

        self._set_active_pane(pane)

        cb = QApplication.clipboard()
        img: QImage = cb.image()
        if img.isNull():
            QMessageBox.information(self, "Paste Image", "Clipboard does not contain an image.")
            self.trace(f"Paste failed (clipboard empty) pane {pane}", "WARN")
            return

        self._flush_page_fields_to_model_and_save()

        safe_item = _sanitize_for_folder(it.name, it.id[:8])
        dst_dir = os.path.join(ASSETS_DIR, safe_item)
        _ensure_dir(dst_dir)

        dst_name = f"{pg.id}_{pane.lower()}_clip_{_now_epoch()}.png"
        dst_rel = _relpath_norm(os.path.join(dst_dir, dst_name))
        dst_abs = _abspath_from_rel(dst_rel)

        ok = img.save(dst_abs, "PNG")
        if not ok:
            QMessageBox.warning(self, "Paste failed", "Clipboard image could not be saved as PNG.")
            self.trace(f"Paste failed (save PNG) pane {pane}", "ERROR")
            return

        if pane == "A":
            pg.image_a_path = dst_rel
            pg.strokes_a = []
        else:
            pg.image_b_path = dst_rel
            pg.strokes_b = []

        pg.updated_at = _now_epoch()
        it.updated_at = _now_epoch()
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._save_db_with_warning()

        viewer.set_image_path(dst_abs)
        viewer.set_strokes([])
        viewer.setFocus(Qt.MouseFocusReason)

        self.trace(f"Pasted image pane {pane}: {dst_rel}", "INFO")

    def _set_image_from_file(self, pane: str, src_path: str) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg:
            return
        if not os.path.isfile(src_path):
            return

        viewer = self.viewer_a if pane == "A" else self.viewer_b
        if viewer is None:
            return

        self._set_active_pane(pane)
        self._flush_page_fields_to_model_and_save()

        ext = os.path.splitext(src_path)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]:
            QMessageBox.warning(self, "Invalid file", "Please select an image file.")
            self.trace(f"Invalid image extension: {ext}", "WARN")
            return

        safe_item = _sanitize_for_folder(it.name, it.id[:8])
        dst_dir = os.path.join(ASSETS_DIR, safe_item)
        _ensure_dir(dst_dir)

        dst_name = f"{pg.id}_{pane.lower()}{ext}"
        dst_rel = _relpath_norm(os.path.join(dst_dir, dst_name))
        dst_abs = _abspath_from_rel(dst_rel)

        try:
            shutil.copy2(src_path, dst_abs)
        except Exception as e:
            QMessageBox.critical(self, "Copy failed", f"Failed to copy image:\n{e}")
            self.trace(f"Copy failed: {e}", "ERROR")
            return

        if pane == "A":
            pg.image_a_path = dst_rel
            pg.strokes_a = []
        else:
            pg.image_b_path = dst_rel
            pg.strokes_b = []

        pg.updated_at = _now_epoch()
        it.updated_at = _now_epoch()
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._save_db_with_warning()

        viewer.set_image_path(dst_abs)
        viewer.set_strokes([])
        viewer.setFocus(Qt.MouseFocusReason)

        self.trace(f"Loaded image pane {pane}: {dst_rel}", "INFO")

    # ---------------- Text/meta utilities ----------------
    def copy_ticker(self) -> None:
        txt = self.edit_ticker.text().strip()
        if not txt:
            QMessageBox.information(self, "Copy Ticker", "Ticker is empty.")
            return
        QApplication.clipboard().setText(txt)
        self.trace(f"Copied ticker: {txt}", "DEBUG")

    # ---------------- Ideas panel toggle ----------------
    def _on_toggle_ideas(self, checked: bool) -> None:
        self._set_global_ideas_visible(checked, persist=True)

    def _set_global_ideas_visible(self, visible: bool, persist: bool = True) -> None:
        self.ideas_panel.setVisible(bool(visible))

        self.btn_ideas.blockSignals(True)
        self.btn_ideas.setChecked(bool(visible))
        self.btn_ideas.blockSignals(False)

        self._update_text_area_layout()

        if persist:
            self.db.ui_state["global_ideas_visible"] = bool(visible)
            self._save_db_with_warning()
            self.trace(f"Global Ideas visible={visible}", "INFO")

    # ---------------- Description toggle ----------------
    def _on_toggle_desc(self, checked: bool) -> None:
        self._set_desc_visible(bool(checked), persist=True)

    def _set_desc_visible(self, visible: bool, persist: bool = True) -> None:
        self._desc_visible = bool(visible)
        self.notes_left.setVisible(self._desc_visible)

        for pane in ("A", "B"):
            ui = self._pane_ui.get(pane, {})
            if ui and "desc_toggle" in ui:
                btn = ui["desc_toggle"]
                btn.blockSignals(True)
                btn.setChecked(self._desc_visible)
                btn.setText("Notes✓" if self._desc_visible else "Notes")
                btn.blockSignals(False)

        self._update_text_area_layout()

        if persist:
            self.db.ui_state["desc_visible"] = bool(self._desc_visible)
            self._save_db_with_warning()
            self.trace(f"Description visible={visible}", "INFO")

    # ---------------- Trace visible toggle ----------------
    def _set_trace_visible(self, visible: bool, persist: bool = True) -> None:
        self._trace_visible = bool(visible)
        self.trace_group.setVisible(self._trace_visible)
        self.trace_show_row.setVisible(not self._trace_visible)

        try:
            total = max(1, self.right_vsplit.height())
            if self._trace_visible:
                rvs = self.db.ui_state.get("right_vsplit_sizes")
                if self._is_valid_splitter_sizes(rvs):
                    self.right_vsplit.setSizes(rvs)
                else:
                    trace_h = 210
                    self.right_vsplit.setSizes([max(1, total - trace_h), trace_h])
            else:
                self.db.ui_state["right_vsplit_sizes"] = self.right_vsplit.sizes()
                self.right_vsplit.setSizes([max(1, total - 38), 38])
        except Exception:
            pass

        if persist:
            self.db.ui_state["trace_visible"] = bool(self._trace_visible)
            self._save_db_with_warning()

    # ---------------- Layout logic (notes/ideas) ----------------
    def _collapse_text_container(self, collapse: bool) -> None:
        if collapse:
            if self.text_container.isVisible():
                self._remember_splitter_sizes()
                self._save_db_with_warning()
            self.text_container.setVisible(False)
            total = max(1, self.page_splitter.width())
            self.page_splitter.setSizes([total, 0])
        else:
            if not self.text_container.isVisible():
                self.text_container.setVisible(True)
            ps = self.db.ui_state.get("page_splitter_sizes")
            if self._is_valid_splitter_sizes(ps):
                self.page_splitter.setSizes(ps)
            else:
                self.page_splitter.setSizes([760, 700])

    def _update_text_area_layout(self) -> None:
        ideas_vis = bool(self.ideas_panel.isVisible())
        desc_vis = bool(self._desc_visible)

        if not desc_vis and not ideas_vis:
            self._collapse_text_container(True)
            return

        self._collapse_text_container(False)

        total = max(1, self.notes_ideas_splitter.width())
        if desc_vis and ideas_vis:
            # split reasonable
            right = max(320, min(520, int(total * 0.34)))
            left = max(220, total - right)
            self.notes_ideas_splitter.setSizes([left, right])
        elif desc_vis and (not ideas_vis):
            self.notes_ideas_splitter.setSizes([total, 0])
        elif (not desc_vis) and ideas_vis:
            self.notes_ideas_splitter.setSizes([0, total])

    # ---------------- Rich text target / sync ----------------
    def _set_active_rich_edit(self, editor: QTextEdit) -> None:
        self._active_rich_edit = editor
        self._sync_format_buttons()

    def _on_any_rich_cursor_changed(self) -> None:
        try:
            snd = self.sender()
        except Exception:
            snd = None
        if snd is not None and snd is self._active_rich_edit:
            self._sync_format_buttons()

    def _apply_format(self, bold: Optional[bool] = None, italic: Optional[bool] = None, underline: Optional[bool] = None) -> None:
        ed = self._active_rich_edit
        if ed is None:
            return

        fmt = QTextCharFormat()
        if bold is not None:
            fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)
        if italic is not None:
            fmt.setFontItalic(bool(italic))
        if underline is not None:
            fmt.setFontUnderline(bool(underline))

        cur = ed.textCursor()
        if cur.hasSelection():
            cur.mergeCharFormat(fmt)
            ed.mergeCurrentCharFormat(fmt)
        else:
            ed.mergeCurrentCharFormat(fmt)

        ed.setFocus(Qt.MouseFocusReason)
        self._on_page_field_changed()

    def _apply_text_color(self, color_hex: str) -> None:
        ed = self._active_rich_edit
        if ed is None:
            return
        c = QColor(color_hex)
        if not c.isValid():
            c = QColor(COLOR_DEFAULT)

        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(c))

        cur = ed.textCursor()
        if cur.hasSelection():
            cur.mergeCharFormat(fmt)
            ed.mergeCurrentCharFormat(fmt)
        else:
            ed.mergeCurrentCharFormat(fmt)

        ed.setFocus(Qt.MouseFocusReason)
        self._on_page_field_changed()

    def _apply_list(self, kind: str) -> None:
        ed = self._active_rich_edit
        if ed is None:
            return
        cur = ed.textCursor()
        style = QTextListFormat.ListDisc if kind == "bullet" else QTextListFormat.ListDecimal
        fmt = QTextListFormat()
        fmt.setStyle(style)

        cur.beginEditBlock()
        try:
            cur.createList(fmt)
        except Exception:
            pass
        cur.endEditBlock()

        ed.setFocus(Qt.MouseFocusReason)
        self._on_page_field_changed()

    def _sync_format_buttons(self) -> None:
        ed = self._active_rich_edit
        if ed is None:
            return
        cf = ed.currentCharFormat()

        is_bold = cf.fontWeight() >= QFont.Bold
        is_italic = bool(cf.fontItalic())
        is_under = bool(cf.fontUnderline())

        self.btn_fmt_bold.blockSignals(True)
        self.btn_fmt_italic.blockSignals(True)
        self.btn_fmt_underline.blockSignals(True)
        self.btn_fmt_bold.setChecked(is_bold)
        self.btn_fmt_italic.setChecked(is_italic)
        self.btn_fmt_underline.setChecked(is_under)
        self.btn_fmt_bold.blockSignals(False)
        self.btn_fmt_italic.blockSignals(False)
        self.btn_fmt_underline.blockSignals(False)

        col = cf.foreground().color() if cf.foreground().style() != Qt.NoBrush else QColor(COLOR_DEFAULT)
        if not col.isValid():
            col = QColor(COLOR_DEFAULT)
        col_hex = col.name().upper()

        def _set_checked(btn: QToolButton, on: bool) -> None:
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)

        if col_hex == QColor(COLOR_RED).name().upper():
            _set_checked(self.btn_col_red, True)
        elif col_hex == QColor(COLOR_BLUE).name().upper():
            _set_checked(self.btn_col_blue, True)
        elif col_hex == QColor(COLOR_YELLOW).name().upper():
            _set_checked(self.btn_col_yellow, True)
        else:
            _set_checked(self.btn_col_default, True)

    # ---------------- List indent/outdent (Tab / Shift+Tab) ----------------
    def _indent_or_outdent_list(self, editor: QTextEdit, delta: int) -> bool:
        cur = editor.textCursor()
        lst = cur.currentList()
        if lst is None:
            return False

        fmt = lst.format()
        indent = int(fmt.indent())
        new_indent = max(1, indent + int(delta))
        if new_indent == indent:
            return True

        fmt.setIndent(new_indent)

        cur.beginEditBlock()
        try:
            cur.createList(fmt)
        except Exception:
            pass
        cur.endEditBlock()

        editor.setTextCursor(cur)
        self._on_page_field_changed()
        return True

    # ---------------- Event filter ----------------
    def eventFilter(self, obj, event) -> bool:
        va = getattr(self, "viewer_a", None)
        vb = getattr(self, "viewer_b", None)

        if va is not None and obj is va.viewport() and event.type() == QEvent.MouseButtonPress:
            self._set_active_pane("A")
            return False
        if vb is not None and obj is vb.viewport() and event.type() == QEvent.MouseButtonPress:
            self._set_active_pane("B")
            return False

        if va is not None and obj is va.viewport() and event.type() == QEvent.Resize:
            self._reposition_overlay("A")
            return super().eventFilter(obj, event)
        if vb is not None and obj is vb.viewport() and event.type() == QEvent.Resize:
            self._reposition_overlay("B")
            return super().eventFilter(obj, event)

        if isinstance(obj, QTextEdit) and event.type() == QEvent.FocusIn:
            self._set_active_rich_edit(obj)
            return super().eventFilter(obj, event)

        if isinstance(obj, QTextEdit) and event.type() == QEvent.KeyPress:
            key = event.key()
            mods = event.modifiers()

            is_tab = (key == Qt.Key_Tab)
            is_backtab = (key == Qt.Key_Backtab) or (is_tab and bool(mods & Qt.ShiftModifier))

            if is_backtab:
                if self._indent_or_outdent_list(obj, delta=-1):
                    return True
                return False

            if is_tab:
                if self._indent_or_outdent_list(obj, delta=+1):
                    return True
                obj.textCursor().insertText("    ")
                self._on_page_field_changed()
                return True

        return super().eventFilter(obj, event)


def main() -> None:
    _ensure_dir("data")
    _ensure_dir(ASSETS_DIR)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


# ============================================================
# Release History (append-only)
# ------------------------------------------------------------
# v0.6.0 (2026-01-01)
# - (ARCH) Folder(Category)/Item 구조로 트리 재구성 + Item만 실제 데이터 보유
# - (UX) Drag&Drop 제거, Move Up/Down으로만 순서 변경
# - (UI) Chart A/B Vertical(원복), Notes는 오른쪽(수평) + Trace 유지
#
# v0.5.1 (2026-01-01)
# - (FIX) Global Ideas 패널 표시/폭 0 문제 보정 + post-init 레이아웃 보정
# - (DEV) Trace 패널(하단) 추가: Vertical Splitter로 높이 조절 + 상태 저장
# ============================================================
