# -*- coding: utf-8 -*-
"""
Trader Chart Note App (PyQt5) - OneNote-style Step/Page Navigator

Version: 0.5.0  (2025-12-28)
Versioning: MAJOR.MINOR.PATCH (SemVer)

Release Notes (v0.5.0):
- (UX) Dual chart image panes (A/B) stacked vertically for 비교 분석
  - Each page can store two images + two independent annotation stroke sets
  - Per-pane Open / Paste / Clear / Fit
  - Per-pane caption overlay (hover/클릭 확장)
  - Click a pane to make it "active" (only affects which overlay is interacted with)
- (FIX) eventFilter now references viewer_a/viewer_b safely (prevents AttributeError during init)
- (UX) List outdent rule:
  - Shift+Tab: outdent ONLY when cursor is inside a list
  - Outside list: let Qt default behavior happen (focus traversal 등 기본 동작)

Existing features:
- Category → Step Tree(좌측), Category/Step Drag & Drop
- Rich Text formatting toolbar (Bold/Italic/Underline) + Ctrl+B/I/U
- Text Color presets (Default/Red/Blue/Yellow)
- List (Bullet/Numbered)
- List indentation (Tab/Shift+Tab) with the rule above
- Description/Checklist/Ideas HTML 저장/로드(plain text 하위호환)
- Safe JSON save (WinError 5 대응)
- 이미지 뷰: Zoom/Pan + Draw(shift 직선) + pen color/width + Clear Lines
- Description 패널 숨김/표시(이미지 뷰 플로팅 Notes 버튼)
- Global Ideas 패널 토글
- Step Tree: Step move / Category reorder(위아래만)

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

APP_TITLE = "Trader Chart Note (v0.5.0)"
DEFAULT_DB_PATH = os.path.join("data", "notes_db.json")
ASSETS_DIR = "assets"

DEFAULT_CHECK_QUESTIONS = [
    "Q. 매집구간이 보이는가?",
    "Q. 매물이 모두 정리가 되었는가? 그럴만한 상승구간과 거래량이 나왔는가?",
    "Q. 그렇지 않다면 지지선, 깨지말아야할 선은 무엇인가?",
    "Q. 돌아서는 구간을 찾을 수 있는가?",
]

# Text color presets
COLOR_DEFAULT = "#222222"
COLOR_RED = "#FF3C3C"
COLOR_BLUE = "#2D6BFF"
COLOR_YELLOW = "#FFD400"


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

    # background-color / background 제거 (hex, rgb, rgba)
    s = re.sub(r'background-color\s*:\s*#[0-9a-fA-F]{3,8}\s*;?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'background-color\s*:\s*rgba?\([^)]+\)\s*;?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'background\s*:\s*#[0-9a-fA-F]{3,8}\s*;?', '', s, flags=re.IGNORECASE)
    s = re.sub(r'background\s*:\s*rgba?\([^)]+\)\s*;?', '', s, flags=re.IGNORECASE)

    # style="" / style=" ; ; " 정리
    s = re.sub(r'style="\s*;+\s*"', '', s, flags=re.IGNORECASE)
    s = re.sub(r'style="\s*"', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\sstyle=""', '', s, flags=re.IGNORECASE)

    # style="...;;" → style="..."
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
# Step Tree with Drag & Drop + Highlight + Guide label
# ---------------------------
class StepTreeWidget(QTreeWidget):
    """
    - Step drag: reorder and move across categories
    - Category drag: reorder top-level categories (prevent nesting by disallowing center drop)
    - During drag: highlight target category and show guide label
    """
    stepStructureDropped = pyqtSignal(str)         # dragged_step_id
    categoryOrderDropped = pyqtSignal(str)         # dragged_category_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_step_id: Optional[str] = None
        self._drag_category_name: Optional[str] = None
        self._drag_node_type: Optional[str] = None  # "step" or "category"

        self._hl_item: Optional[QTreeWidgetItem] = None
        self._hl_brush = QBrush(QColor(90, 141, 255, 55))  # light blue
        self._hl_clear_brush = QBrush()

        self._guide = QLabel(self.viewport())
        self._guide.setVisible(False)
        self._guide.setStyleSheet("""
            QLabel {
                background: rgba(20,20,20,170);
                color: white;
                padding: 6px 10px;
                border-radius: 10px;
                font-size: 11px;
            }
        """)

    def _set_guide(self, text: str, pos: QPoint) -> None:
        if not text:
            self._guide.setVisible(False)
            return
        self._guide.setText(text)
        self._guide.adjustSize()

        x = pos.x() + 14
        y = pos.y() + 14
        vw = self.viewport().width()
        vh = self.viewport().height()
        gw = self._guide.width()
        gh = self._guide.height()
        x = max(6, min(vw - gw - 6, x))
        y = max(6, min(vh - gh - 6, y))
        self._guide.move(x, y)
        self._guide.setVisible(True)

    def _clear_guide(self) -> None:
        self._guide.setVisible(False)

    def _set_highlight_category_item(self, cat_item: Optional[QTreeWidgetItem]) -> None:
        if self._hl_item is cat_item:
            return
        if self._hl_item is not None:
            self._hl_item.setBackground(0, self._hl_clear_brush)
        self._hl_item = cat_item
        if self._hl_item is not None:
            self._hl_item.setBackground(0, self._hl_brush)

    def _clear_highlight(self) -> None:
        self._set_highlight_category_item(None)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return

        node_type = item.data(0, MainWindow.NODE_TYPE_ROLE)
        if node_type not in ("step", "category"):
            return

        self._drag_node_type = str(node_type)
        self._drag_step_id = None
        self._drag_category_name = None

        if node_type == "step":
            sid = item.data(0, MainWindow.STEP_ID_ROLE)
            self._drag_step_id = str(sid) if sid else None
        else:
            cat = item.data(0, MainWindow.CATEGORY_NAME_ROLE)
            if not cat:
                cat = item.text(0)
            self._drag_category_name = str(cat).strip() if cat else None

        super().startDrag(supportedActions)

    def dragEnterEvent(self, event) -> None:
        super().dragEnterEvent(event)
        self._clear_highlight()
        self._clear_guide()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)
        self._clear_highlight()
        self._clear_guide()

    def _resolve_target_category_item(self, pos: QPoint) -> Tuple[Optional[QTreeWidgetItem], str]:
        it = self.itemAt(pos)
        if not it:
            return None, ""
        ntype = it.data(0, MainWindow.NODE_TYPE_ROLE)
        if ntype == "category":
            return it, (it.text(0) or "").strip()
        if ntype == "step":
            parent = it.parent()
            if parent:
                return parent, (parent.text(0) or "").strip()
        return None, ""

    def dragMoveEvent(self, event) -> None:
        pos = event.pos()

        if self._drag_node_type == "category":
            it = self.itemAt(pos)
            if it is None:
                self._clear_highlight()
                self._clear_guide()
                event.ignore()
                return

            ntype = it.data(0, MainWindow.NODE_TYPE_ROLE)
            if ntype == "step" and it.parent() is not None:
                it = it.parent()

            if it.data(0, MainWindow.NODE_TYPE_ROLE) != "category":
                self._clear_highlight()
                self._clear_guide()
                event.ignore()
                return

            rect = self.visualItemRect(it)
            y = pos.y()
            top_band = rect.top() + int(rect.height() * 0.33)
            bottom_band = rect.bottom() - int(rect.height() * 0.33)

            if top_band <= y <= bottom_band:
                self._set_highlight_category_item(it)
                self._set_guide(f"Reorder Category ↕ (drop above/below): {it.text(0)}", pos)
                event.ignore()
                return

            self._set_highlight_category_item(it)
            self._set_guide(f"Reorder Category ↕ : {it.text(0)}", pos)
            event.accept()
            super().dragMoveEvent(event)
            return

        if self._drag_node_type == "step":
            cat_item, cat_name = self._resolve_target_category_item(pos)
            if cat_item is not None and cat_name:
                self._set_highlight_category_item(cat_item)
                self._set_guide(f"Move Step → {cat_name}", pos)
                event.accept()
            else:
                self._clear_highlight()
                self._clear_guide()
            super().dragMoveEvent(event)
            return

        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)

        self._clear_highlight()
        self._clear_guide()

        if self._drag_node_type == "step" and self._drag_step_id:
            self.stepStructureDropped.emit(self._drag_step_id)
        elif self._drag_node_type == "category" and self._drag_category_name:
            self.categoryOrderDropped.emit(self._drag_category_name)

        self._drag_node_type = None
        self._drag_step_id = None
        self._drag_category_name = None


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

    # Dual chart panes
    image_a_path: str
    image_b_path: str
    image_a_caption: str
    image_b_caption: str
    strokes_a: Strokes
    strokes_b: Strokes

    # Notes/meta
    note_text: str
    stock_name: str
    ticker: str
    checklist: Checklist
    created_at: int
    updated_at: int


@dataclass
class Step:
    id: str
    name: str
    category: str
    pages: List[Page]
    last_page_index: int = 0


class NoteDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.data: Dict[str, Any] = {}
        self.steps: List[Step] = []
        self.ui_state: Dict[str, Any] = {}
        self.category_order: List[str] = []
        self.global_ideas: str = ""  # HTML
        self.load()

    def load(self) -> None:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

        if not self.data:
            self.data = self._default_data()

        self.ui_state = self.data.get("ui_state", {})
        if not isinstance(self.ui_state, dict):
            self.ui_state = {}

        # ensure keys
        self.ui_state.setdefault("global_ideas_visible", False)
        self.ui_state.setdefault("desc_visible", True)
        self.ui_state.setdefault("page_splitter_sizes", None)
        self.ui_state.setdefault("notes_splitter_sizes", None)

        self.steps = self._parse_steps(self.data.get("steps", []))
        if not self.steps:
            self.steps = self._parse_steps(self._default_data()["steps"])

        for st in self.steps:
            if not st.pages:
                st.pages.append(self.new_page())

        raw_order = self.data.get("category_order", [])
        if isinstance(raw_order, list):
            self.category_order = [str(x).strip() for x in raw_order if str(x).strip()]
        else:
            self.category_order = []

        self.global_ideas = str(self.data.get("global_ideas", "") or "")
        self._ensure_category_order_consistency()

    def save(self) -> bool:
        self.data["version"] = "0.5.0"
        self.data["updated_at"] = _now_epoch()
        self.data["steps"] = self._serialize_steps(self.steps)
        self.data["ui_state"] = self.ui_state
        self.data["category_order"] = self.category_order
        self.data["global_ideas"] = self.global_ideas

        ok = _safe_write_json(self.db_path, self.data)
        self.data["_last_save_ok"] = bool(ok)
        if not ok:
            self.data["_last_save_failed_at"] = _now_epoch()
        return ok

    @staticmethod
    def _default_data() -> Dict[str, Any]:
        step_names = ["Step 1", "Step 2", "Step 3"]
        steps = []
        for name in step_names:
            steps.append(
                {
                    "id": _uuid(),
                    "name": name,
                    "category": "General",
                    "last_page_index": 0,
                    "pages": [
                        {
                            "id": _uuid(),

                            "image_a_path": "",
                            "image_b_path": "",
                            "image_a_caption": "",
                            "image_b_caption": "",
                            "strokes_a": [],
                            "strokes_b": [],

                            "note_text": "",
                            "stock_name": "",
                            "ticker": "",
                            "checklist": _default_checklist(),
                            "created_at": _now_epoch(),
                            "updated_at": _now_epoch(),
                        }
                    ],
                }
            )
        return {
            "version": "0.5.0",
            "created_at": _now_epoch(),
            "updated_at": _now_epoch(),
            "steps": steps,
            "ui_state": {
                "global_ideas_visible": False,
                "desc_visible": True,
                "page_splitter_sizes": None,
                "notes_splitter_sizes": None,
            },
            "category_order": ["General"],
            "global_ideas": "",
        }

    @staticmethod
    def _parse_steps(steps_raw: List[Dict[str, Any]]) -> List[Step]:
        steps: List[Step] = []
        for s in steps_raw:
            pages_raw = s.get("pages", [])
            pages: List[Page] = []
            for p in pages_raw:
                # Backward compatibility:
                # - v0.4.x stored: image_path, image_caption, strokes (or annotations)
                # - v0.5.0 stores: image_a_path/image_b_path, image_a_caption/image_b_caption, strokes_a/strokes_b
                image_a_path = str(p.get("image_a_path", p.get("image_path", "")) or "")
                image_b_path = str(p.get("image_b_path", "") or "")

                image_a_caption = str(p.get("image_a_caption", p.get("image_caption", "")) or "")
                image_b_caption = str(p.get("image_b_caption", "") or "")

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
                        created_at=int(p.get("created_at", _now_epoch())),
                        updated_at=int(p.get("updated_at", _now_epoch())),
                    )
                )

            category = str(s.get("category", "General")).strip() or "General"

            steps.append(
                Step(
                    id=str(s.get("id", _uuid())),
                    name=str(s.get("name", "Untitled Step")),
                    category=category,
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
                    "category": st.category,
                    "last_page_index": st.last_page_index,
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

    def _current_categories_set(self) -> List[str]:
        return sorted({(s.category or "General").strip() or "General" for s in self.steps})

    def _ensure_category_order_consistency(self) -> None:
        existing = set(self._current_categories_set())
        self.category_order = [c for c in self.category_order if c in existing]

        for c in self._current_categories_set():
            if c not in self.category_order:
                self.category_order.append(c)

        if not self.category_order:
            self.category_order = ["General"]

    def list_categories(self) -> List[str]:
        self._ensure_category_order_consistency()
        return list(self.category_order)

    def get_step_by_id(self, step_id: str) -> Optional[Step]:
        for st in self.steps:
            if st.id == step_id:
                return st
        return None

    def add_step(self, name: str, category: str) -> Step:
        category = (category or "").strip() or "General"
        st = Step(id=_uuid(), name=name, category=category, pages=[self.new_page()], last_page_index=0)
        self.steps.append(st)
        if category not in self.category_order:
            self.category_order.append(category)
        return st

    def delete_step(self, step_id: str) -> bool:
        if len(self.steps) <= 1:
            return False
        self.steps = [s for s in self.steps if s.id != step_id]
        self._ensure_category_order_consistency()
        return True

    def rename_category(self, old: str, new: str) -> None:
        old = (old or "").strip() or "General"
        new = (new or "").strip() or "General"
        if old == new:
            return

        for st in self.steps:
            if (st.category or "General").strip() == old:
                st.category = new

        if old in self.category_order:
            if new in self.category_order:
                self.category_order = [c for c in self.category_order if c != old]
            else:
                self.category_order = [new if c == old else c for c in self.category_order]
        else:
            if new not in self.category_order:
                self.category_order.append(new)

        self._ensure_category_order_consistency()

    def delete_category_move_steps(self, cat: str, move_to: str) -> None:
        cat = (cat or "").strip() or "General"
        move_to = (move_to or "").strip() or "General"
        if cat == move_to:
            return
        for st in self.steps:
            if (st.category or "General").strip() == cat:
                st.category = move_to
        self.category_order = [c for c in self.category_order if c != cat]
        if move_to not in self.category_order:
            self.category_order.append(move_to)
        self._ensure_category_order_consistency()

    def delete_category_and_steps(self, cat: str) -> bool:
        cat = (cat or "").strip() or "General"
        remaining = [s for s in self.steps if (s.category or "General").strip() != cat]
        if not remaining:
            return False
        self.steps = remaining
        self.category_order = [c for c in self.category_order if c != cat]
        self._ensure_category_order_consistency()
        return True

    def move_category(self, cat: str, direction: int) -> None:
        cat = (cat or "").strip() or "General"
        self._ensure_category_order_consistency()
        if cat not in self.category_order:
            return
        idx = self.category_order.index(cat)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.category_order):
            return
        self.category_order[idx], self.category_order[new_idx] = self.category_order[new_idx], self.category_order[idx]


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
    STEP_ID_ROLE = Qt.UserRole + 101
    NODE_TYPE_ROLE = Qt.UserRole + 102  # "category" or "step"
    CATEGORY_NAME_ROLE = Qt.UserRole + 103

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1460, 960)

        self.db = NoteDB(DEFAULT_DB_PATH)

        self.current_step_id: Optional[str] = None
        self.current_page_index: int = 0
        self._loading_ui: bool = False

        self._active_rich_edit: Optional[QTextEdit] = None

        # Description visible state
        self._desc_visible: bool = bool(self.db.ui_state.get("desc_visible", True))
        self._page_split_prev_sizes: Optional[List[int]] = None
        self._notes_split_prev_sizes: Optional[List[int]] = None

        # FIX: prevent eventFilter crashing during init
        self.viewer_a: Optional[ZoomPanAnnotateView] = None
        self.viewer_b: Optional[ZoomPanAnnotateView] = None

        self._active_pane: str = "A"  # "A" or "B"

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_page_fields_to_model_and_save)

        self._last_save_warn_ts: float = 0.0
        self._save_warn_cooldown_sec: float = 10.0

        # overlay objects per pane: {"A": {...}, "B": {...}}
        self._pane_ui: Dict[str, Dict[str, Any]] = {}

        self._build_ui()
        self._build_pane_overlays()

        # Splitter moved save hooks
        self.page_splitter.splitterMoved.connect(self._on_page_splitter_moved)
        self.notes_ideas_splitter.splitterMoved.connect(self._on_notes_splitter_moved)

        self._load_ui_state_or_defaults()
        self._apply_splitter_sizes_from_state()

        self._refresh_steps_tree(select_current=True)
        self._load_current_page_to_ui()
        self._load_global_ideas_to_ui()

        # Apply panel visibilities
        ideas_vis = bool(self.db.ui_state.get("global_ideas_visible", False))
        self._set_global_ideas_visible(ideas_vis, persist=False)
        self._set_desc_visible(bool(self.db.ui_state.get("desc_visible", True)), persist=False)

        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_prev_page)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.go_next_page)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_page)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.force_save)

        # Text formatting shortcuts (active text box)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.btn_fmt_bold.toggle())
        QShortcut(QKeySequence("Ctrl+I"), self, activated=lambda: self.btn_fmt_italic.toggle())
        QShortcut(QKeySequence("Ctrl+U"), self, activated=lambda: self.btn_fmt_underline.toggle())

        # Viewer-specific paste shortcuts (avoid stealing paste from QTextEdit)
        if self.viewer_a is not None:
            QShortcut(QKeySequence("Ctrl+V"), self.viewer_a, activated=lambda: self.paste_image_from_clipboard("A"))
        if self.viewer_b is not None:
            QShortcut(QKeySequence("Ctrl+V"), self.viewer_b, activated=lambda: self.paste_image_from_clipboard("B"))

        # After init, ensure layout is consistent with states
        self._update_text_area_layout()

    def closeEvent(self, event) -> None:
        try:
            self._flush_page_fields_to_model_and_save()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- Splitter persistence helpers ----------------
    def _is_valid_splitter_sizes(self, v: Any) -> bool:
        return (
            isinstance(v, list)
            and len(v) == 2
            and all(isinstance(x, int) for x in v)
            and v[0] >= 0 and v[1] >= 0
        )

    def _remember_page_splitter_sizes(self) -> None:
        sizes = self.page_splitter.sizes()
        if self._is_valid_splitter_sizes(sizes):
            self._page_split_prev_sizes = list(sizes)
            self.db.ui_state["page_splitter_sizes"] = list(sizes)

    def _remember_notes_splitter_sizes(self) -> None:
        sizes = self.notes_ideas_splitter.sizes()
        if self._is_valid_splitter_sizes(sizes):
            self._notes_split_prev_sizes = list(sizes)
            self.db.ui_state["notes_splitter_sizes"] = list(sizes)

    def _on_page_splitter_moved(self, pos: int, index: int) -> None:
        if self._loading_ui:
            return
        if not self.text_container.isVisible():
            return
        self._remember_page_splitter_sizes()
        self._save_db_with_warning()

    def _on_notes_splitter_moved(self, pos: int, index: int) -> None:
        if self._loading_ui:
            return
        if not self.notes_left.isVisible():
            return
        if not self.ideas_panel.isVisible():
            return
        self._remember_notes_splitter_sizes()
        self._save_db_with_warning()

    def _apply_splitter_sizes_from_state(self) -> None:
        self._loading_ui = True
        try:
            ps = self.db.ui_state.get("page_splitter_sizes")
            if self._is_valid_splitter_sizes(ps):
                self._page_split_prev_sizes = list(ps)
                try:
                    self.page_splitter.setSizes(ps)
                except Exception:
                    pass

            ns = self.db.ui_state.get("notes_splitter_sizes")
            if self._is_valid_splitter_sizes(ns):
                self._notes_split_prev_sizes = list(ns)
                try:
                    self.notes_ideas_splitter.setSizes(ns)
                except Exception:
                    pass
        finally:
            self._loading_ui = False

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)

        main_splitter = QSplitter(Qt.Horizontal, root)

        # Left: category tree
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        step_controls = QWidget()
        step_controls_layout = FlowLayout(step_controls, margin=0, spacing=6)

        self.btn_add_step = QToolButton()
        self.btn_add_step.setText("+ Step")
        self.btn_rename_step = QToolButton()
        self.btn_rename_step.setText("Rename Step")
        self.btn_set_category = QToolButton()
        self.btn_set_category.setText("Set Category")
        self.btn_del_step = QToolButton()
        self.btn_del_step.setText("Del Step")

        self.btn_add_step.clicked.connect(self.add_step)
        self.btn_rename_step.clicked.connect(self.rename_step)
        self.btn_set_category.clicked.connect(self.set_step_category)
        self.btn_del_step.clicked.connect(self.delete_step)

        step_controls_layout.addWidget(self.btn_add_step)
        step_controls_layout.addWidget(self.btn_rename_step)
        step_controls_layout.addWidget(self.btn_set_category)
        step_controls_layout.addWidget(self.btn_del_step)

        self.steps_tree = StepTreeWidget()
        self.steps_tree.setHeaderHidden(True)
        self.steps_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.steps_tree.setUniformRowHeights(True)

        self.steps_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.steps_tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        self.steps_tree.setDragEnabled(True)
        self.steps_tree.setAcceptDrops(True)
        self.steps_tree.setDropIndicatorShown(True)
        self.steps_tree.setDefaultDropAction(Qt.MoveAction)
        self.steps_tree.setDragDropMode(QAbstractItemView.InternalMove)

        self.steps_tree.stepStructureDropped.connect(lambda _: self._rebuild_db_from_tree())
        self.steps_tree.categoryOrderDropped.connect(lambda _: self._rebuild_db_from_tree())

        left_layout.addWidget(step_controls)
        left_layout.addWidget(self.steps_tree, 1)

        # Right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.page_splitter = QSplitter(Qt.Horizontal)

        # ---------------- Image section (dual panes) ----------------
        self.img_container = QWidget()
        img_layout = QVBoxLayout(self.img_container)
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

        # Dual-pane splitter
        self.dual_view_splitter = QSplitter(Qt.Vertical)
        self.dual_view_splitter.setChildrenCollapsible(False)

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

        self.dual_view_splitter.addWidget(paneA)
        self.dual_view_splitter.addWidget(paneB)
        self.dual_view_splitter.setStretchFactor(0, 1)
        self.dual_view_splitter.setStretchFactor(1, 1)
        self.dual_view_splitter.setSizes([420, 420])

        img_layout.addWidget(self.dual_view_splitter, 1)

        # Page nav
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

        # ---------------- Text section ----------------
        self.text_container = QWidget()
        text_layout = QVBoxLayout(self.text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        # ====== Toolbar (2 rows, compact) ======
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

        # --- B/I/U ---
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

        # --- Color buttons (exclusive) ---
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

        # --- List buttons ---
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

        # Ideas toggle
        self.btn_ideas = QToolButton()
        self.btn_ideas.setText("Ideas")
        self.btn_ideas.setToolTip("Toggle Global Ideas panel (전역 아이디어)")
        self.btn_ideas.setCheckable(True)
        self.btn_ideas.toggled.connect(self._on_toggle_ideas)

        # ---- Row1 ----
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

        # ---- Row2 ----
        row2 = QWidget()
        r2 = QHBoxLayout(row2)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(6)

        # Text color
        r2.addWidget(self.btn_col_default)
        r2.addWidget(self.btn_col_red)
        r2.addWidget(self.btn_col_blue)
        r2.addWidget(self.btn_col_yellow)

        r2.addWidget(_vsep())

        # Lists
        r2.addWidget(self.btn_bullets)
        r2.addWidget(self.btn_numbered)

        r2.addStretch(1)

        fmt_outer.addWidget(row1)
        fmt_outer.addWidget(row2)

        self.notes_ideas_splitter = QSplitter(Qt.Horizontal)

        # Left: Checklist + Description
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
            note.setTabChangesFocus(False)  # IMPORTANT for Tab indentation
            self.chk_notes.append(note)

            chk_layout.addWidget(cb)
            chk_layout.addWidget(note)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("추가 분석/설명을 자유롭게 작성하세요... (서식/색상 가능)")
        self.text_edit.textChanged.connect(self._on_page_field_changed)
        self.text_edit.installEventFilter(self)
        self.text_edit.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
        self.text_edit.setTabChangesFocus(False)  # IMPORTANT for Tab indentation

        notes_left_l.addWidget(self.chk_group)
        notes_left_l.addWidget(self.text_edit, 1)

        # Right: Ideas
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

        ideas_header = QWidget()
        ideas_header_l = QHBoxLayout(ideas_header)
        ideas_header_l.setContentsMargins(0, 0, 0, 0)
        ideas_header_l.setSpacing(6)

        self.lbl_ideas = QLabel("Global Ideas")
        self.lbl_ideas.setStyleSheet("font-weight: 700;")
        ideas_header_l.addWidget(self.lbl_ideas, 1)

        self.edit_global_ideas = QTextEdit()
        self.edit_global_ideas.setPlaceholderText("전역적으로 적용할 아이디어를 여기에 작성하세요... (서식/색상 가능)")
        self.edit_global_ideas.textChanged.connect(self._on_page_field_changed)
        self.edit_global_ideas.installEventFilter(self)
        self.edit_global_ideas.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
        self.edit_global_ideas.setTabChangesFocus(False)  # IMPORTANT for Tab indentation

        ideas_l.addWidget(ideas_header)
        ideas_l.addWidget(self.edit_global_ideas, 1)

        self.notes_ideas_splitter.addWidget(self.notes_left)
        self.notes_ideas_splitter.addWidget(self.ideas_panel)
        self.notes_ideas_splitter.setChildrenCollapsible(False)
        self.notes_ideas_splitter.setCollapsible(0, True)
        self.notes_ideas_splitter.setCollapsible(1, True)
        self.notes_ideas_splitter.setStretchFactor(0, 3)
        self.notes_ideas_splitter.setStretchFactor(1, 1)

        text_layout.addWidget(fmt_row)
        text_layout.addWidget(self.notes_ideas_splitter, 1)

        self.page_splitter.addWidget(self.img_container)
        self.page_splitter.addWidget(self.text_container)
        self.page_splitter.setStretchFactor(0, 1)
        self.page_splitter.setStretchFactor(1, 1)

        right_layout.addWidget(self.page_splitter, 1)

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([340, 1120])

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

        # Encourage image area
        self.text_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.img_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.text_container.setMinimumWidth(440)

        # Default active editor
        self._set_active_rich_edit(self.text_edit)

        # Default checked states
        self.btn_col_default.setChecked(True)

    # ---------------- overlays for pane A/B ----------------
    def _build_pane_overlays(self) -> None:
        self._pane_ui = {}
        self._pane_ui["A"] = self._build_overlay_for_pane("A", self.viewer_a)
        self._pane_ui["B"] = self._build_overlay_for_pane("B", self.viewer_b)

        # Initial active pane
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
        anno_panel.setObjectName(f"anno_panel_{pane}")
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

        help_lbl = QLabel(
            "• Wheel: Zoom\n"
            "• Drag: Pan (Draw OFF)\n"
            "• Drag: Draw (Draw ON)\n"
            "• Shift+Drag: Straight line\n"
            "• Ctrl+V: Paste image (viewer focused)\n"
            "• Alt+←/→: Prev/Next\n"
            "• Ctrl+N: Add page, Ctrl+S: Save\n"
            "• Ctrl+B/I/U: Text Bold/Italic/Underline (active text box)\n"
            "• Text Color: Default/Red/Blue/Yellow\n"
            "• List: Bullet/Numbered\n"
            "• List indent: Tab / Shift+Tab\n"
            "• Notes button: Description 패널 숨김/표시",
            anno_panel
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color:#555; font-size: 11px;")
        p_layout.addWidget(help_lbl)

        def apply_pen():
            color_hex = str(combo_color.currentData())
            width = float(combo_width.currentData())
            viewer.set_pen(color_hex, width)

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

        btn_clear_lines.clicked.connect(clear_lines)

        def open_panel():
            self._set_active_pane(pane)
            btn_anno_toggle.setVisible(False)
            anno_panel.setVisible(True)
            self._reposition_overlay(pane)

        def close_panel():
            if btn_draw_mode.isChecked():
                btn_draw_mode.setChecked(False)
                viewer.set_mode_pan()
            anno_panel.setVisible(False)
            btn_anno_toggle.setVisible(True)
            self._reposition_overlay(pane)

        btn_anno_toggle.clicked.connect(open_panel)
        btn_anno_close.clicked.connect(close_panel)

        # initial position
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
        # Visual hint: slightly different border
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
            btn_desc_toggle.move(
                max(margin, w - btn_desc_toggle.width() - margin),
                margin + btn_anno_toggle.height() + gap
            )

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

    # ---------------- v0.4.x+: rebuild model from current tree ----------------
    def _rebuild_db_from_tree(self) -> None:
        self._flush_page_fields_to_model_and_save()

        by_id: Dict[str, Step] = {s.id: s for s in self.db.steps}

        new_cat_order: List[str] = []
        new_steps: List[Step] = []
        seen: set = set()

        for ti in range(self.steps_tree.topLevelItemCount()):
            cat_item = self.steps_tree.topLevelItem(ti)
            cat_name = str(cat_item.text(0)).strip() or "General"
            if cat_name not in new_cat_order:
                new_cat_order.append(cat_name)

            for ci in range(cat_item.childCount()):
                step_item = cat_item.child(ci)
                sid = step_item.data(0, self.STEP_ID_ROLE)
                if not sid:
                    continue
                sid = str(sid)
                st = by_id.get(sid)
                if not st:
                    continue
                st.category = cat_name
                new_steps.append(st)
                seen.add(sid)

        for st in self.db.steps:
            if st.id not in seen:
                new_steps.append(st)
                if st.category and st.category not in new_cat_order:
                    new_cat_order.append(st.category)

        self.db.steps = new_steps
        self.db.category_order = new_cat_order
        self.db._ensure_category_order_consistency()

        if self.current_step_id and not self.db.get_step_by_id(self.current_step_id):
            self.current_step_id = self.db.steps[0].id if self.db.steps else None
            self.current_page_index = 0

        self._save_ui_state()
        self._save_db_with_warning()

        self._refresh_steps_tree(select_current=True)
        self._load_current_page_to_ui()

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

        # B/I/U
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

        # Text Color sync
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
        """
        Returns True if handled.
        - If cursor is in a list: indent/outdent list level by delta
        - Else: return False
        """
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

    # ---------------- Ideas panel toggle ----------------
    def _on_toggle_ideas(self, checked: bool) -> None:
        self._set_global_ideas_visible(checked, persist=True)

    def _set_global_ideas_visible(self, visible: bool, persist: bool = True) -> None:
        if (not visible) and self.notes_left.isVisible() and self.ideas_panel.isVisible():
            self._remember_notes_splitter_sizes()

        self.ideas_panel.setVisible(bool(visible))

        self.btn_ideas.blockSignals(True)
        self.btn_ideas.setChecked(bool(visible))
        self.btn_ideas.blockSignals(False)

        self._update_text_area_layout()

        if persist:
            self.db.ui_state["global_ideas_visible"] = bool(visible)
            self._save_db_with_warning()

    # ---------------- Description toggle ----------------
    def _on_toggle_desc(self, checked: bool) -> None:
        self._set_desc_visible(bool(checked), persist=True)

    def _set_desc_visible(self, visible: bool, persist: bool = True) -> None:
        if (not visible) and self.notes_left.isVisible() and self.ideas_panel.isVisible():
            self._remember_notes_splitter_sizes()

        self._desc_visible = bool(visible)
        self.notes_left.setVisible(self._desc_visible)

        # Sync both pane buttons
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

    def _collapse_text_container(self, collapse: bool) -> None:
        if collapse:
            if self.text_container.isVisible():
                self._remember_page_splitter_sizes()
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
            elif self._page_split_prev_sizes and len(self._page_split_prev_sizes) == 2:
                self.page_splitter.setSizes(self._page_split_prev_sizes)
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
            ns = self.db.ui_state.get("notes_splitter_sizes")
            if self._is_valid_splitter_sizes(ns):
                self.notes_ideas_splitter.setSizes(ns)
            elif self._notes_split_prev_sizes and len(self._notes_split_prev_sizes) == 2:
                self.notes_ideas_splitter.setSizes(self._notes_split_prev_sizes)
            else:
                right = max(320, min(520, int(total * 0.34)))
                left = max(1, total - right)
                self.notes_ideas_splitter.setSizes([left, right])

        elif desc_vis and (not ideas_vis):
            self.notes_ideas_splitter.setSizes([total, 0])

        elif (not desc_vis) and ideas_vis:
            self.notes_ideas_splitter.setSizes([0, total])

    # ---------------- Context menu ----------------
    def _on_tree_context_menu(self, pos) -> None:
        item = self.steps_tree.itemAt(pos)
        if not item:
            return

        node_type = item.data(0, self.NODE_TYPE_ROLE)

        if node_type == "category":
            cat = str(item.data(0, self.CATEGORY_NAME_ROLE) or "").strip() or "General"

            menu = QMenu(self)
            act_add_step = menu.addAction("+ Step in this Category")
            act_rename_cat = menu.addAction("Rename Category")
            act_delete_cat = menu.addAction("Delete Category")
            menu.addSeparator()
            act_move_up = menu.addAction("Move Category Up")
            act_move_down = menu.addAction("Move Category Down")

            cats = self.db.list_categories()
            try:
                idx = cats.index(cat)
            except ValueError:
                idx = -1
            act_move_up.setEnabled(idx > 0)
            act_move_down.setEnabled(0 <= idx < len(cats) - 1)

            chosen = menu.exec_(self.steps_tree.viewport().mapToGlobal(pos))
            if not chosen:
                return

            if chosen == act_add_step:
                self._ctx_add_step_in_category(cat)
            elif chosen == act_rename_cat:
                self._ctx_rename_category(cat)
            elif chosen == act_delete_cat:
                self._ctx_delete_category(cat)
            elif chosen == act_move_up:
                self._ctx_move_category(cat, -1)
            elif chosen == act_move_down:
                self._ctx_move_category(cat, +1)
            return

        if node_type == "step":
            sid = str(item.data(0, self.STEP_ID_ROLE) or "")
            st = self.db.get_step_by_id(sid)
            if not st:
                return

            menu = QMenu(self)
            act_rename = menu.addAction("Rename Step")
            act_set_cat = menu.addAction("Set Category")
            act_delete = menu.addAction("Delete Step")

            chosen = menu.exec_(self.steps_tree.viewport().mapToGlobal(pos))
            if not chosen:
                return

            if chosen == act_rename:
                self.rename_step()
            elif chosen == act_set_cat:
                self.set_step_category()
            elif chosen == act_delete:
                self.delete_step()
            return

    # ---------------- Category ops ----------------
    def _ctx_add_step_in_category(self, cat: str) -> None:
        self._flush_page_fields_to_model_and_save()
        name, ok = QInputDialog.getText(self, "Add Step", f"Step name (Category: {cat}):", text="New Step")
        if not ok or not name.strip():
            return
        st = self.db.add_step(name.strip(), cat)
        self.current_step_id = st.id
        self.current_page_index = 0
        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_steps_tree(select_current=True)
        self._load_current_page_to_ui()

    def _ctx_rename_category(self, old_cat: str) -> None:
        new_cat, ok = QInputDialog.getText(self, "Rename Category", "New category name:", text=old_cat)
        if not ok:
            return
        new_cat = (new_cat or "").strip()
        if not new_cat:
            return

        self._flush_page_fields_to_model_and_save()
        self.db.rename_category(old_cat, new_cat)
        self._save_db_with_warning()
        self._refresh_steps_tree(select_current=True)

    def _ctx_delete_category(self, cat: str) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Category")
        msg.setText(f"Category '{cat}' 처리 방식을 선택하세요.")
        btn_move = msg.addButton("Move Steps to Another Category", QMessageBox.ActionRole)
        btn_delete = msg.addButton("Delete Steps in This Category", QMessageBox.DestructiveRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_cancel)
        msg.exec_()

        clicked = msg.clickedButton()
        if clicked == btn_cancel:
            return

        self._flush_page_fields_to_model_and_save()

        if clicked == btn_move:
            cats = [c for c in self.db.list_categories() if c != cat]
            hint = ", ".join(cats) if cats else "General"
            target, ok = QInputDialog.getText(
                self,
                "Move Steps",
                f"Move steps to category (existing: {hint}):",
                text=(cats[0] if cats else "General"),
            )
            if not ok:
                return
            target = (target or "").strip() or "General"

            self.db.delete_category_move_steps(cat, target)
            if self.current_step_id and not self.db.get_step_by_id(self.current_step_id):
                self.current_step_id = self.db.steps[0].id
                self.current_page_index = 0

            self._save_ui_state()
            self._save_db_with_warning()
            self._refresh_steps_tree(select_current=True)
            self._load_current_page_to_ui()
            return

        if clicked == btn_delete:
            ok = self.db.delete_category_and_steps(cat)
            if not ok:
                QMessageBox.warning(self, "Not allowed", "이 Category 삭제는 모든 Step을 제거하게 되어 허용되지 않습니다.")
                return

            if self.current_step_id and not self.db.get_step_by_id(self.current_step_id):
                self.current_step_id = self.db.steps[0].id
                self.current_page_index = max(
                    0, min(self.db.steps[0].last_page_index, len(self.db.steps[0].pages) - 1)
                )

            self._save_ui_state()
            self._save_db_with_warning()
            self._refresh_steps_tree(select_current=True)
            self._load_current_page_to_ui()
            return

    def _ctx_move_category(self, cat: str, direction: int) -> None:
        self.db.move_category(cat, direction)
        self._save_db_with_warning()
        self._refresh_steps_tree(select_current=True)

    # ---------------- State helpers ----------------
    def _load_ui_state_or_defaults(self) -> None:
        step_id = self.db.ui_state.get("selected_step_id")
        page_idx = self.db.ui_state.get("current_page_index", 0)

        if step_id and self.db.get_step_by_id(step_id):
            self.current_step_id = step_id
        else:
            self.current_step_id = self.db.steps[0].id if self.db.steps else None

        self.current_page_index = int(page_idx) if isinstance(page_idx, int) else 0

        st = self.current_step()
        if st and st.pages:
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

    def _save_ui_state(self) -> None:
        self.db.ui_state["selected_step_id"] = self.current_step_id
        self.db.ui_state["current_page_index"] = self.current_page_index
        self.db.ui_state["desc_visible"] = bool(self._desc_visible)
        self.db.ui_state["global_ideas_visible"] = bool(self.ideas_panel.isVisible())

        if self.text_container.isVisible():
            self._remember_page_splitter_sizes()
        if self.notes_left.isVisible() and self.ideas_panel.isVisible():
            self._remember_notes_splitter_sizes()

    # ---------------- Tree: category -> steps ----------------
    def _refresh_steps_tree(self, select_current: bool = False) -> None:
        self.steps_tree.blockSignals(True)
        self.steps_tree.clear()

        cats = self.db.list_categories()
        cat_nodes: Dict[str, QTreeWidgetItem] = {}

        for cat in cats:
            top = QTreeWidgetItem([cat])
            top.setData(0, self.NODE_TYPE_ROLE, "category")
            top.setData(0, self.CATEGORY_NAME_ROLE, cat)
            flags = top.flags()
            flags |= Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
            top.setFlags(flags)
            self.steps_tree.addTopLevelItem(top)
            cat_nodes[cat] = top

        selected_item: Optional[QTreeWidgetItem] = None
        for st in self.db.steps:
            cat = (st.category or "General").strip() or "General"
            if cat not in cat_nodes:
                top = QTreeWidgetItem([cat])
                top.setData(0, self.NODE_TYPE_ROLE, "category")
                top.setData(0, self.CATEGORY_NAME_ROLE, cat)
                flags = top.flags()
                flags |= Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
                top.setFlags(flags)
                self.steps_tree.addTopLevelItem(top)
                cat_nodes[cat] = top

            child = QTreeWidgetItem([st.name])
            child.setData(0, self.NODE_TYPE_ROLE, "step")
            child.setData(0, self.STEP_ID_ROLE, st.id)
            flags = child.flags()
            flags |= Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
            child.setFlags(flags)

            cat_nodes[cat].addChild(child)

            if select_current and st.id == self.current_step_id:
                selected_item = child

        for i in range(self.steps_tree.topLevelItemCount()):
            self.steps_tree.topLevelItem(i).setExpanded(True)

        if selected_item:
            self.steps_tree.setCurrentItem(selected_item)

        self.steps_tree.blockSignals(False)

    def _on_tree_selection_changed(self) -> None:
        item = self.steps_tree.currentItem()
        if not item:
            return

        if item.data(0, self.NODE_TYPE_ROLE) != "step":
            return

        step_id = item.data(0, self.STEP_ID_ROLE)
        if not step_id:
            return

        if str(step_id) == self.current_step_id:
            return

        self._flush_page_fields_to_model_and_save()

        self.current_step_id = str(step_id)
        st = self.current_step()
        if not st:
            return

        self.current_page_index = max(0, min(st.last_page_index, len(st.pages) - 1))
        self._save_ui_state()
        self._load_current_page_to_ui()

    # ---------------- Safe save wrapper ----------------
    def _save_db_with_warning(self) -> bool:
        ok = self.db.save()
        if ok:
            return True

        now = time.time()
        if (now - self._last_save_warn_ts) >= self._save_warn_cooldown_sec:
            self._last_save_warn_ts = now
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
    def _load_current_page_to_ui(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
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
                self._update_nav()
            finally:
                self._loading_ui = False
            return

        self._loading_ui = True
        try:
            self.edit_stock_name.setText(pg.stock_name or "")
            self.edit_ticker.setText(pg.ticker or "")

            # Pane captions
            capA = pg.image_a_caption or ""
            capB = pg.image_b_caption or ""
            if self._pane_ui.get("A"):
                self._pane_ui["A"]["cap"].setPlainText(capA)
            if self._pane_ui.get("B"):
                self._pane_ui["B"]["cap"].setPlainText(capB)

            # Pane images
            if self.viewer_a is not None:
                if pg.image_a_path:
                    abs_a = _abspath_from_rel(pg.image_a_path)
                    if os.path.exists(abs_a):
                        self.viewer_a.set_image_path(abs_a)
                    else:
                        self.viewer_a.clear_image()
                else:
                    self.viewer_a.clear_image()
                self.viewer_a.set_strokes(pg.strokes_a or [])
                self.viewer_a.set_mode_pan()

            if self.viewer_b is not None:
                if pg.image_b_path:
                    abs_b = _abspath_from_rel(pg.image_b_path)
                    if os.path.exists(abs_b):
                        self.viewer_b.set_image_path(abs_b)
                    else:
                        self.viewer_b.clear_image()
                else:
                    self.viewer_b.clear_image()
                self.viewer_b.set_strokes(pg.strokes_b or [])
                self.viewer_b.set_mode_pan()

            # Checklist
            cl = _normalize_checklist(pg.checklist)
            for i in range(len(DEFAULT_CHECK_QUESTIONS)):
                self.chk_boxes[i].setChecked(bool(cl[i].get("checked", False)))
                val = str(cl[i].get("note", "") or "")
                val = _strip_highlight_html(val)
                if _looks_like_html(val):
                    self.chk_notes[i].setHtml(val)
                else:
                    self.chk_notes[i].setPlainText(val)

            # Description
            val_desc = pg.note_text or ""
            val_desc = _strip_highlight_html(val_desc)
            if _looks_like_html(val_desc):
                self.text_edit.setHtml(val_desc)
            else:
                self.text_edit.setPlainText(val_desc)

            # close overlay panels & reset draw
            for pane in ("A", "B"):
                ui = self._pane_ui.get(pane, {})
                if ui:
                    ui["draw"].setChecked(False)
                    ui["panel"].setVisible(False)
                    ui["anno_toggle"].setVisible(True)
                    self._reposition_overlay(pane)

            self._update_nav()
            self._set_active_rich_edit(self.text_edit)
            self._sync_format_buttons()
        finally:
            self._loading_ui = False

    def _on_page_field_changed(self) -> None:
        if self._loading_ui:
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
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg or self._loading_ui:
            return

        changed = False

        new_global = _strip_highlight_html(self.edit_global_ideas.toHtml())
        if self.db.global_ideas != new_global:
            self.db.global_ideas = new_global
            changed = True

        # captions
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

        # strokes
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

        st.last_page_index = self.current_page_index
        self._save_ui_state()

        if changed:
            pg.updated_at = _now_epoch()

        self._save_db_with_warning()

    def force_save(self) -> None:
        self._flush_page_fields_to_model_and_save()
        QMessageBox.information(self, "Saved", "Save requested (check warnings if file is locked).")

    def _update_nav(self) -> None:
        st = self.current_step()
        total = len(st.pages) if st else 0
        cur = (self.current_page_index + 1) if total > 0 else 0
        self.lbl_page.setText(f"{cur} / {total}")

        self.btn_prev.setEnabled(total > 0 and self.current_page_index > 0)
        self.btn_next.setEnabled(total > 0 and self.current_page_index < total - 1)
        self.btn_del_page.setEnabled(total > 1)

    # ---------------- Global ideas load ----------------
    def _load_global_ideas_to_ui(self) -> None:
        self._loading_ui = True
        try:
            val = self.db.global_ideas or ""
            val = _strip_highlight_html(val)
            if _looks_like_html(val):
                self.edit_global_ideas.setHtml(val)
            else:
                self.edit_global_ideas.setPlainText(val)
        finally:
            self._loading_ui = False

    # ---------------- Page navigation ----------------
    def go_prev_page(self) -> None:
        st = self.current_step()
        if not st or self.current_page_index <= 0:
            return
        self._flush_page_fields_to_model_and_save()
        self.current_page_index -= 1
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self._load_current_page_to_ui()

    def go_next_page(self) -> None:
        st = self.current_step()
        if not st or self.current_page_index >= len(st.pages) - 1:
            return
        self._flush_page_fields_to_model_and_save()
        self.current_page_index += 1
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self._load_current_page_to_ui()

    def add_page(self) -> None:
        st = self.current_step()
        if not st:
            return
        self._flush_page_fields_to_model_and_save()

        insert_at = self.current_page_index + 1
        st.pages.insert(insert_at, self.db.new_page())
        self.current_page_index = insert_at
        st.last_page_index = self.current_page_index

        self._save_ui_state()
        self._save_db_with_warning()
        self._load_current_page_to_ui()

    def delete_page(self) -> None:
        st = self.current_step()
        if not st or len(st.pages) <= 1:
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
        del st.pages[self.current_page_index]
        self.current_page_index = max(0, min(self.current_page_index, len(st.pages) - 1))
        st.last_page_index = self.current_page_index

        self._save_ui_state()
        self._save_db_with_warning()
        self._load_current_page_to_ui()

    # ---------------- Image handling (dual panes) ----------------
    def reset_image_view(self, pane: str) -> None:
        viewer = self.viewer_a if pane == "A" else self.viewer_b
        if viewer is None:
            return
        self._set_active_pane(pane)
        viewer.fit_to_view()
        viewer.setFocus(Qt.MouseFocusReason)

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
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
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
        self._save_db_with_warning()
        viewer.clear_image()

    def paste_image_from_clipboard(self, pane: str) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            return

        viewer = self.viewer_a if pane == "A" else self.viewer_b
        if viewer is None:
            return

        self._set_active_pane(pane)

        cb = QApplication.clipboard()
        img: QImage = cb.image()
        if img.isNull():
            QMessageBox.information(self, "Paste Image", "Clipboard does not contain an image.")
            return

        self._flush_page_fields_to_model_and_save()

        safe_step = _sanitize_for_folder(st.name, st.id[:8])
        dst_dir = os.path.join(ASSETS_DIR, safe_step)
        _ensure_dir(dst_dir)

        dst_name = f"{pg.id}_{pane.lower()}_clip_{_now_epoch()}.png"
        dst_rel = _relpath_norm(os.path.join(dst_dir, dst_name))
        dst_abs = _abspath_from_rel(dst_rel)

        ok = img.save(dst_abs, "PNG")
        if not ok:
            QMessageBox.warning(self, "Paste failed", "Clipboard image could not be saved as PNG.")
            return

        if pane == "A":
            pg.image_a_path = dst_rel
            pg.strokes_a = []
        else:
            pg.image_b_path = dst_rel
            pg.strokes_b = []

        pg.updated_at = _now_epoch()
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self._save_db_with_warning()

        viewer.set_image_path(dst_abs)
        viewer.set_strokes([])
        viewer.setFocus(Qt.MouseFocusReason)

    def _set_image_from_file(self, pane: str, src_path: str) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
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
            return

        safe_step = _sanitize_for_folder(st.name, st.id[:8])
        dst_dir = os.path.join(ASSETS_DIR, safe_step)
        _ensure_dir(dst_dir)

        dst_name = f"{pg.id}_{pane.lower()}{ext}"
        dst_rel = _relpath_norm(os.path.join(dst_dir, dst_name))
        dst_abs = _abspath_from_rel(dst_rel)

        try:
            shutil.copy2(src_path, dst_abs)
        except Exception as e:
            QMessageBox.critical(self, "Copy failed", f"Failed to copy image:\n{e}")
            return

        if pane == "A":
            pg.image_a_path = dst_rel
            pg.strokes_a = []
        else:
            pg.image_b_path = dst_rel
            pg.strokes_b = []

        pg.updated_at = _now_epoch()
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self._save_db_with_warning()

        viewer.set_image_path(dst_abs)
        viewer.set_strokes([])
        viewer.setFocus(Qt.MouseFocusReason)

    # ---------------- Text/meta utilities ----------------
    def copy_ticker(self) -> None:
        txt = self.edit_ticker.text().strip()
        if not txt:
            QMessageBox.information(self, "Copy Ticker", "Ticker is empty.")
            return
        QApplication.clipboard().setText(txt)

    # ---------------- Step management ----------------
    def add_step(self) -> None:
        self._flush_page_fields_to_model_and_save()

        name, ok = QInputDialog.getText(self, "Add Step", "Step name:", text="New Step")
        if not ok or not name.strip():
            return

        cats = self.db.list_categories()
        hint = ", ".join(cats) if cats else "General"
        cat_text, ok2 = QInputDialog.getText(self, "Category", f"Category tag (existing: {hint}):", text="General")
        if not ok2:
            return

        category = (cat_text or "").strip() or "General"
        st = self.db.add_step(name.strip(), category)
        self.current_step_id = st.id
        self.current_page_index = 0

        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_steps_tree(select_current=True)
        self._load_current_page_to_ui()

    def rename_step(self) -> None:
        st = self.current_step()
        if not st:
            return

        new_name, ok = QInputDialog.getText(self, "Rename Step", "New name:", text=st.name)
        if not ok or not new_name.strip():
            return

        st.name = new_name.strip()
        self._save_db_with_warning()
        self._refresh_steps_tree(select_current=True)

    def set_step_category(self) -> None:
        st = self.current_step()
        if not st:
            return

        cats = self.db.list_categories()
        hint = ", ".join(cats) if cats else "General"
        new_cat, ok = QInputDialog.getText(
            self,
            "Set Category",
            f"Category tag (existing: {hint}):",
            text=(st.category or "General"),
        )
        if not ok:
            return

        st.category = (new_cat or "").strip() or "General"
        if st.category not in self.db.category_order:
            self.db.category_order.append(st.category)
        self._save_db_with_warning()
        self._refresh_steps_tree(select_current=True)

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
            f"Delete step '{st.name}' (Category: {st.category}) and all its pages?\n(This cannot be undone.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        ok = self.db.delete_step(st.id)
        if not ok:
            QMessageBox.warning(self, "Failed", "Cannot delete the last remaining step.")
            return

        self.current_step_id = self.db.steps[0].id
        first = self.db.steps[0]
        self.current_page_index = max(0, min(first.last_page_index, len(first.pages) - 1))
        self._save_ui_state()
        self._save_db_with_warning()

        self._refresh_steps_tree(select_current=True)
        self._load_current_page_to_ui()

    # ---------------- Event filter ----------------
    def eventFilter(self, obj, event) -> bool:
        va = getattr(self, "viewer_a", None)
        vb = getattr(self, "viewer_b", None)

        # Click on pane viewport -> set active pane
        if va is not None and obj is va.viewport() and event.type() == QEvent.MouseButtonPress:
            self._set_active_pane("A")
            return False
        if vb is not None and obj is vb.viewport() and event.type() == QEvent.MouseButtonPress:
            self._set_active_pane("B")
            return False

        # Viewport resize -> reposition overlays
        if va is not None and obj is va.viewport() and event.type() == QEvent.Resize:
            self._reposition_overlay("A")
            return super().eventFilter(obj, event)
        if vb is not None and obj is vb.viewport() and event.type() == QEvent.Resize:
            self._reposition_overlay("B")
            return super().eventFilter(obj, event)

        # Focus handling: set active editor
        if isinstance(obj, QTextEdit) and event.type() == QEvent.FocusIn:
            self._set_active_rich_edit(obj)
            return super().eventFilter(obj, event)

        # Key handling: Tab / Shift+Tab list indent/outdent
        if isinstance(obj, QTextEdit) and event.type() == QEvent.KeyPress:
            key = event.key()
            mods = event.modifiers()

            is_tab = (key == Qt.Key_Tab)
            is_backtab = (key == Qt.Key_Backtab) or (is_tab and bool(mods & Qt.ShiftModifier))

            if is_backtab:
                # Shift+Tab: outdent ONLY when in list. Otherwise, default behavior.
                if self._indent_or_outdent_list(obj, delta=-1):
                    return True
                return False

            if is_tab:
                # Tab: indent list if in list, else insert spaces
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
