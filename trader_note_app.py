# -*- coding: utf-8 -*-
"""
Trader Chart Note App (PyQt5) - Folder(Item) Navigator

Version: 0.7.5  (2026-01-01)

v0.7.5 변경 사항:
- Description 숨김 시 Chart 영역 우측 끝까지 확장 개선
  AS-IS: Description 숨김 시 Chart 영역이 우측으로 넓어지지만 윈도우 끝까지 확장되지 않음
  TO-BE:
    - Description 영역의 최소 크기를 0으로 설정하여 완전히 접을 수 있도록
    - 핸들 너비를 8px에서 5px로 줄여 Chart가 더 넓게 차지하도록
    - 재시도 횟수 증가 (300ms 추가) 및 크기 검증 로직 개선
    - Description 표시 시 최소 크기(440px) 복원

v0.7.4 변경 사항:
- Description 숨김 시 Chart 영역 확장
  AS-IS: Description 숨김 시에도 Description 영역이 10px로 유지되어 Chart 영역이 제한됨
  TO-BE: Description 숨김 시 Chart 영역이 거의 전체를 차지하도록 확장 (splitter 핸들만 8px 유지)
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

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF, QRect, QPoint, QEvent, QSize
from PyQt5.QtGui import (
    QImage, QPixmap, QPainterPath, QPen, QColor, QPainter, QIcon,
    QTextCharFormat, QTextListFormat, QFont, QBrush, QKeySequence
)
from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QGraphicsPixmapItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QShortcut, QSplitter, QTextEdit, QToolButton,
    QVBoxLayout, QHBoxLayout, QWidget, QInputDialog, QComboBox, QCheckBox, QGroupBox, QPushButton,
    QLayout, QWidgetItem, QFrame, QTreeWidget, QTreeWidgetItem, QMenu, QPlainTextEdit,
    QAbstractItemView, QButtonGroup, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QSplitterHandle
)

APP_TITLE = "Trader Chart Note (v0.7.5)"
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


def _now_epoch() -> int:
    return int(time.time())


def _uuid() -> str:
    return str(uuid.uuid4())


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _safe_write_json(path: str, data: Dict[str, Any], retries: int = 12, base_delay: float = 0.08) -> bool:
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


def _make_copy_icon(size: int = 16) -> QIcon:
    """복사 아이콘: 두 개의 겹쳐진 사각형 (클립보드 모양)"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    
    # 배경 사각형 (뒤쪽)
    bg_color = QColor("#E0E0E0")
    bg_pen = QPen(bg_color, 1.0)
    p.setPen(bg_pen)
    p.setBrush(QBrush(bg_color))
    back_rect = QRect(5, 2, 10, 12)
    p.drawRoundedRect(back_rect, 1.5, 1.5)
    
    # 앞쪽 사각형 (클립보드)
    fg_color = QColor("#333333")
    fg_pen = QPen(fg_color, 1.2)
    p.setPen(fg_pen)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    front_rect = QRect(3, 4, 10, 12)
    p.drawRoundedRect(front_rect, 1.5, 1.5)
    
    # 클립보드 상단 클립 부분
    clip_rect = QRect(6, 4, 4, 3)
    p.setBrush(QBrush(fg_color))
    p.drawRoundedRect(clip_rect, 0.5, 0.5)
    
    # 클립보드 내부 라인 (문서 느낌)
    line_pen = QPen(QColor("#CCCCCC"), 0.8)
    p.setPen(line_pen)
    p.drawLine(5, 9, 11, 9)
    p.drawLine(5, 11, 11, 11)
    
    p.end()
    return QIcon(pm)


def _make_expand_icon(size: int = 16, expanded: bool = False) -> QIcon:
    """사각형 안에 + 모양 확장/축소 아이콘 생성 (축소: +, 확장: -)"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    
    # 사각형 테두리
    border_color = QColor("#999999")
    border_pen = QPen(border_color, 1.5)
    p.setPen(border_pen)
    p.setBrush(QBrush(QColor("#FFFFFF")))
    
    # 사각형 그리기 (약간의 여백)
    margin = 2
    rect = QRect(margin, margin, size - margin * 2, size - margin * 2)
    p.drawRect(rect)
    
    # + 또는 - 기호 그리기
    fg = QColor("#333333")
    pen = QPen(fg, 2.0)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    
    center = size // 2
    line_len = 6
    
    # 가로선 (항상 표시)
    p.drawLine(center - line_len // 2, center, center + line_len // 2, center)
    
    # 세로선 (축소 상태일 때만 + 모양)
    if not expanded:
        p.drawLine(center, center - line_len // 2, center, center + line_len // 2)
    
    p.end()
    return QIcon(pm)


# ---------------------------
# Custom Tree Delegate for + expand icon
# ---------------------------
class PlusTreeDelegate(QStyledItemDelegate):
    """+ 모양 확장 아이콘을 그리는 커스텀 델리게이트"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tree_widget = parent
    
    def paint(self, painter, option, index):
        # 기본 페인팅 수행
        super().paint(painter, option, index)
        
        # QTreeWidget에서 아이템 가져오기
        if self._tree_widget is None:
            return
        
        item = self._tree_widget.itemFromIndex(index)
        if item is None:
            return
        
        # 자식이 있는 경우에만 + 모양 그리기
        if item.childCount() > 0:
            # 확장 아이콘 영역 계산 (보통 왼쪽에 위치)
            icon_rect = QRect(option.rect.x() + 2, option.rect.y() + (option.rect.height() - 12) // 2, 12, 12)
            
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor("#666666"), 2.0)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            
            center_x = icon_rect.x() + icon_rect.width() // 2
            center_y = icon_rect.y() + icon_rect.height() // 2
            line_len = 6
            
            # 가로선
            painter.drawLine(center_x - line_len // 2, center_y, center_x + line_len // 2, center_y)
            
            # 세로선 (축소 상태일 때만 + 모양)
            if not item.isExpanded():
                painter.drawLine(center_x, center_y - line_len // 2, center_x, center_y + line_len // 2)
            
            painter.restore()


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
    category_id: str
    pages: List[Page]
    last_page_index: int = 0


@dataclass
class Category:
    id: str
    name: str
    parent_id: Optional[str]
    child_ids: List[str]
    item_ids: List[str]


class NoteDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.data: Dict[str, Any] = {}
        self.categories: Dict[str, Category] = {}
        self.items: Dict[str, Item] = {}
        self.root_category_ids: List[str] = []
        self.ui_state: Dict[str, Any] = {}
        self.global_ideas: str = ""
        self.load()

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
        root_id = _uuid()
        item_id = _uuid()
        page_id = _uuid()

        return {
            "version": "0.6.0",
            "created_at": now,
            "updated_at": now,
            "root_category_ids": [root_id],
            "categories": [
                {"id": root_id, "name": "General", "parent_id": None, "child_ids": [], "item_ids": [item_id]}
            ],
            "items": [
                {
                    "id": item_id,
                    "name": "Item 1",
                    "category_id": root_id,
                    "last_page_index": 0,
                    "pages": [
                        {
                            "id": page_id,
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
                            "created_at": now,
                            "updated_at": now,
                        }
                    ],
                }
            ],
            "ui_state": {
                "selected_category_id": root_id,
                "selected_item_id": item_id,
                "current_page_index": 0,
                "global_ideas_visible": False,
                "desc_visible": True,
                "page_splitter_sizes": None,
                "notes_splitter_sizes": None,
                "trace_visible": True,
                "right_vsplit_sizes": None,
            },
            "global_ideas": "",
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

        self.ui_state = self.data.get("ui_state", {})
        if not isinstance(self.ui_state, dict):
            self.ui_state = {}

        self.ui_state.setdefault("selected_category_id", "")
        self.ui_state.setdefault("selected_item_id", "")
        self.ui_state.setdefault("current_page_index", 0)
        self.ui_state.setdefault("global_ideas_visible", False)
        self.ui_state.setdefault("desc_visible", True)
        self.ui_state.setdefault("page_splitter_sizes", None)
        self.ui_state.setdefault("notes_splitter_sizes", None)
        self.ui_state.setdefault("trace_visible", True)
        self.ui_state.setdefault("right_vsplit_sizes", None)

        self.global_ideas = str(self.data.get("global_ideas", "") or "")

        self._parse_categories_items(self.data)
        self._ensure_integrity()

    def save(self) -> bool:
        self.data["version"] = "0.6.0"
        self.data["updated_at"] = _now_epoch()
        self.data["ui_state"] = self.ui_state
        self.data["global_ideas"] = self.global_ideas
        self.data["root_category_ids"] = list(self.root_category_ids)
        self.data["categories"] = [self._serialize_category(self.categories[cid]) for cid in self._all_category_ids_in_stable_order()]
        self.data["items"] = [self._serialize_item(self.items[iid]) for iid in self._all_item_ids_in_stable_order()]
        ok = _safe_write_json(self.db_path, self.data)
        return ok

    def _parse_categories_items(self, raw: Dict[str, Any]) -> None:
        self.categories = {}
        self.items = {}
        self.root_category_ids = []

        root_ids = raw.get("root_category_ids", [])
        if isinstance(root_ids, list):
            self.root_category_ids = [str(x) for x in root_ids if str(x)]
        else:
            self.root_category_ids = []

        cats = raw.get("categories", [])
        if isinstance(cats, list):
            for c in cats:
                try:
                    cid = str(c.get("id", _uuid()))
                    name = str(c.get("name", "Folder")).strip() or "Folder"
                    parent_id = c.get("parent_id", None)
                    parent_id = str(parent_id) if parent_id else None
                    child_ids = c.get("child_ids", [])
                    item_ids = c.get("item_ids", [])
                    if not isinstance(child_ids, list):
                        child_ids = []
                    if not isinstance(item_ids, list):
                        item_ids = []
                    self.categories[cid] = Category(
                        id=cid, name=name, parent_id=parent_id,
                        child_ids=[str(x) for x in child_ids if str(x)],
                        item_ids=[str(x) for x in item_ids if str(x)],
                    )
                except Exception:
                    continue

        its = raw.get("items", [])
        if isinstance(its, list):
            for it in its:
                try:
                    iid = str(it.get("id", _uuid()))
                    name = str(it.get("name", "Item")).strip() or "Item"
                    cat_id = str(it.get("category_id", "")) or ""
                    last_page_index = int(it.get("last_page_index", 0))

                    pages_raw = it.get("pages", [])
                    pages: List[Page] = []
                    if isinstance(pages_raw, list):
                        for p in pages_raw:
                            pages.append(
                                Page(
                                    id=str(p.get("id", _uuid())),
                                    image_a_path=str(p.get("image_a_path", "")) or "",
                                    image_b_path=str(p.get("image_b_path", "")) or "",
                                    image_a_caption=str(p.get("image_a_caption", "")) or "",
                                    image_b_caption=str(p.get("image_b_caption", "")) or "",
                                    strokes_a=_normalize_strokes(p.get("strokes_a", [])),
                                    strokes_b=_normalize_strokes(p.get("strokes_b", [])),
                                    note_text=str(p.get("note_text", "")) or "",
                                    stock_name=str(p.get("stock_name", "")) or "",
                                    ticker=str(p.get("ticker", "")) or "",
                                    checklist=_normalize_checklist(p.get("checklist", None)),
                                    created_at=int(p.get("created_at", _now_epoch())),
                                    updated_at=int(p.get("updated_at", _now_epoch())),
                                )
                            )
                    if not pages:
                        pages = [self.new_page()]

                    self.items[iid] = Item(
                        id=iid, name=name, category_id=cat_id, pages=pages, last_page_index=last_page_index
                    )
                except Exception:
                    continue

    def _serialize_page(self, pg: Page) -> Dict[str, Any]:
        return {
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

    def _serialize_item(self, it: Item) -> Dict[str, Any]:
        return {
            "id": it.id,
            "name": it.name,
            "category_id": it.category_id,
            "last_page_index": it.last_page_index,
            "pages": [self._serialize_page(p) for p in it.pages],
        }

    def _serialize_category(self, c: Category) -> Dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "child_ids": list(c.child_ids),
            "item_ids": list(c.item_ids),
        }

    def _ensure_integrity(self) -> None:
        # 카테고리가 없어도 허용 (사용자가 모든 폴더를 삭제할 수 있도록)
        # 초기 로드 시에만 _default_data()를 사용 (load() 함수에서 처리)
        # if not self.categories:
        #     base = self._default_data()
        #     self._parse_categories_items(base)
        #     self.root_category_ids = base["root_category_ids"]

        if not self.root_category_ids:
            self.root_category_ids = [cid for cid, c in self.categories.items() if not c.parent_id]
            if not self.root_category_ids and self.categories:
                self.root_category_ids = [next(iter(self.categories.keys()))]

        for cid, c in self.categories.items():
            c.child_ids = [x for x in c.child_ids if x in self.categories and self.categories[x].parent_id == cid]
            c.item_ids = [x for x in c.item_ids if x in self.items and self.items[x].category_id == cid]

        root0 = self.root_category_ids[0] if self.root_category_ids else None
        for iid, it in self.items.items():
            if it.category_id not in self.categories and root0:
                it.category_id = root0

        for cid, c in self.categories.items():
            owned = [iid for iid, it in self.items.items() if it.category_id == cid]
            for iid in owned:
                if iid not in c.item_ids:
                    c.item_ids.append(iid)

        # 아이템이 없어도 허용 (사용자가 모든 아이템을 삭제할 수 있도록)
        # if not self.items:
        #     root0 = self.root_category_ids[0]
        #     iid = _uuid()
        #     it = Item(id=iid, name="Item 1", category_id=root0, pages=[self.new_page()], last_page_index=0)
        #     self.items[iid] = it
        #     self.categories[root0].item_ids.append(iid)

        for it in self.items.values():
            if not it.pages:
                it.pages = [self.new_page()]
            it.last_page_index = max(0, min(int(it.last_page_index), len(it.pages) - 1))

    def _all_category_ids_in_stable_order(self) -> List[str]:
        out: List[str] = []
        seen = set()

        def dfs(cid: str):
            if cid in seen or cid not in self.categories:
                return
            seen.add(cid)
            out.append(cid)
            for ch in self.categories[cid].child_ids:
                dfs(ch)

        for r in self.root_category_ids:
            dfs(r)
        for cid in self.categories.keys():
            if cid not in seen:
                dfs(cid)
        return out

    def _all_item_ids_in_stable_order(self) -> List[str]:
        out: List[str] = []
        seen = set()
        for cid in self._all_category_ids_in_stable_order():
            c = self.categories.get(cid)
            if not c:
                continue
            for iid in c.item_ids:
                if iid in self.items and iid not in seen:
                    out.append(iid)
                    seen.add(iid)
        for iid in self.items.keys():
            if iid not in seen:
                out.append(iid)
        return out

    def get_category(self, cid: str) -> Optional[Category]:
        return self.categories.get(cid)

    def get_item(self, iid: str) -> Optional[Item]:
        return self.items.get(iid)

    def find_item(self, iid: str) -> Optional[Tuple[Item, Category]]:
        it = self.items.get(iid)
        if not it:
            return None
        cat = self.categories.get(it.category_id)
        if not cat:
            return None
        return it, cat

    def total_items(self) -> int:
        return len(self.items)

    def add_category(self, name: str, parent_id: Optional[str]) -> Category:
        name = (name or "").strip() or "Folder"
        if parent_id and parent_id not in self.categories:
            parent_id = None
        cid = _uuid()
        c = Category(id=cid, name=name, parent_id=parent_id, child_ids=[], item_ids=[])
        self.categories[cid] = c
        if parent_id:
            self.categories[parent_id].child_ids.append(cid)
        else:
            self.root_category_ids.append(cid)
        return c

    def rename_category(self, cid: str, new_name: str) -> None:
        c = self.categories.get(cid)
        if not c:
            return
        new_name = (new_name or "").strip()
        if not new_name:
            return
        c.name = new_name

    def move_category_sibling(self, cid: str, direction: int) -> None:
        c = self.categories.get(cid)
        if not c:
            return
        siblings = self.categories[c.parent_id].child_ids if c.parent_id and c.parent_id in self.categories else self.root_category_ids
        if cid not in siblings:
            return
        idx = siblings.index(cid)
        new_idx = idx + int(direction)
        if new_idx < 0 or new_idx >= len(siblings):
            return
        siblings[idx], siblings[new_idx] = siblings[new_idx], siblings[idx]

    def delete_category_move_to_parent(self, cid: str) -> bool:
        c = self.categories.get(cid)
        if not c:
            return False

        # 루트 폴더인 경우 다른 루트 폴더로 이동, 없으면 빈 상태 허용
        parent_id = c.parent_id if c.parent_id in self.categories else None
        if not parent_id:
            # 루트 폴더인 경우: 다른 루트 폴더가 있으면 그곳으로, 없으면 None (빈 상태 허용)
            other_roots = [rid for rid in self.root_category_ids if rid != cid]
            if other_roots:
                parent_id = other_roots[0]
            else:
                # 마지막 루트 폴더 삭제 시 빈 상태 허용 (자동 생성하지 않음)
                parent_id = None
        target = self.categories[parent_id] if parent_id else None

        for ch_id in list(c.child_ids):
            ch = self.categories.get(ch_id)
            if not ch:
                continue
            ch.parent_id = parent_id
            if target:
                if ch_id not in target.child_ids:
                    target.child_ids.append(ch_id)
            else:
                if ch_id not in self.root_category_ids:
                    self.root_category_ids.append(ch_id)

        for iid in list(c.item_ids):
            it = self.items.get(iid)
            if not it:
                continue
            it.category_id = parent_id if parent_id else (self.root_category_ids[0] if self.root_category_ids else "")
            if parent_id and target:
                if iid not in target.item_ids:
                    target.item_ids.append(iid)
            else:
                root0 = self.root_category_ids[0] if self.root_category_ids else None
                if root0 and iid not in self.categories[root0].item_ids:
                    self.categories[root0].item_ids.append(iid)

        if parent_id and parent_id in self.categories:
            self.categories[parent_id].child_ids = [x for x in self.categories[parent_id].child_ids if x != cid]
        else:
            self.root_category_ids = [x for x in self.root_category_ids if x != cid]

        del self.categories[cid]
        self._ensure_integrity()
        return True

    def delete_category_recursive(self, cid: str) -> bool:
        if cid not in self.categories:
            return False

        to_delete_cats: List[str] = []

        def dfs(x: str):
            if x not in self.categories:
                return
            to_delete_cats.append(x)
            for ch in list(self.categories[x].child_ids):
                dfs(ch)

        dfs(cid)

        to_delete_items: List[str] = []
        for x in to_delete_cats:
            cat = self.categories.get(x)
            if cat:
                to_delete_items.extend([iid for iid in cat.item_ids if iid in self.items])

        # 아이템이 몇 개 있든 삭제 허용 (_ensure_integrity()가 빈 상태를 자동으로 처리함)

        c = self.categories[cid]
        if c.parent_id and c.parent_id in self.categories:
            self.categories[c.parent_id].child_ids = [x for x in self.categories[c.parent_id].child_ids if x != cid]
        else:
            self.root_category_ids = [x for x in self.root_category_ids if x != cid]

        for iid in set(to_delete_items):
            it = self.items.get(iid)
            if not it:
                continue
            cat = self.categories.get(it.category_id)
            if cat:
                cat.item_ids = [x for x in cat.item_ids if x != iid]
            del self.items[iid]

        for x in reversed(to_delete_cats):
            if x in self.categories:
                del self.categories[x]

        self._ensure_integrity()
        return True

    def add_item(self, name: str, category_id: str) -> Item:
        name = (name or "").strip() or "New Item"
        if category_id not in self.categories:
            category_id = self.root_category_ids[0] if self.root_category_ids else ""
        iid = _uuid()
        it = Item(id=iid, name=name, category_id=category_id, pages=[self.new_page()], last_page_index=0)
        self.items[iid] = it
        if category_id and category_id in self.categories:
            self.categories[category_id].item_ids.append(iid)
        return it

    def rename_item(self, iid: str, new_name: str) -> None:
        it = self.items.get(iid)
        if not it:
            return
        new_name = (new_name or "").strip()
        if not new_name:
            return
        it.name = new_name

    def move_item_sibling(self, iid: str, direction: int) -> None:
        it = self.items.get(iid)
        if not it:
            return
        cat = self.categories.get(it.category_id)
        if not cat:
            return
        arr = cat.item_ids
        if iid not in arr:
            return
        idx = arr.index(iid)
        new_idx = idx + int(direction)
        if new_idx < 0 or new_idx >= len(arr):
            return
        arr[idx], arr[new_idx] = arr[new_idx], arr[idx]

    def move_item_to_category(self, iid: str, target_category_id: str) -> bool:
        """아이템을 다른 폴더로 이동"""
        it = self.items.get(iid)
        if not it:
            return False
        if target_category_id not in self.categories:
            return False
        
        old_cat_id = it.category_id
        if old_cat_id == target_category_id:
            return False  # 같은 폴더로 이동할 필요 없음
        
        # 기존 폴더에서 제거
        old_cat = self.categories.get(old_cat_id)
        if old_cat:
            old_cat.item_ids = [x for x in old_cat.item_ids if x != iid]
        
        # 새 폴더에 추가
        new_cat = self.categories[target_category_id]
        if iid not in new_cat.item_ids:
            new_cat.item_ids.append(iid)
        
        # 아이템의 category_id 업데이트
        it.category_id = target_category_id
        
        self._ensure_integrity()
        return True

    def delete_item(self, iid: str) -> bool:
        if iid not in self.items:
            return False
        # 마지막 아이템도 삭제 허용 (빈 상태 허용)
        it = self.items[iid]
        cat = self.categories.get(it.category_id)
        if cat:
            cat.item_ids = [x for x in cat.item_ids if x != iid]
        del self.items[iid]
        self._ensure_integrity()
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
        self._strokes.append({"color": self._stroke_color_hex, "width": self._stroke_width, "points": self._current_points})
        self._reset_current()
        self.strokesChanged.emit()

    def _reset_current(self) -> None:
        self._is_drawing = False
        self._current_item = None
        self._current_path = None
        self._current_points = []
        self._stroke_start = None


# ---------------------------
# Custom Splitter Handle with Toggle Button
# ---------------------------
class DescriptionToggleSplitterHandle(QSplitterHandle):
    """Description 영역 토글 버튼이 있는 커스텀 Splitter 핸들"""
    
    def __init__(self, orientation: Qt.Orientation, parent: QSplitter, toggle_callback) -> None:
        super().__init__(orientation, parent)
        self.toggle_callback = toggle_callback
        self._desc_visible = True
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """UI 설정"""
        # 핸들 배경 스타일 설정
        self.setStyleSheet("""
            QSplitterHandle {
                background-color: #E0E0E0;
                border: 1px solid #B0B0B0;
            }
            QSplitterHandle:hover {
                background-color: #D0D0D0;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 화살표 버튼
        self.toggle_btn = QToolButton(self)
        self.toggle_btn.setFixedSize(32, 50)
        self.toggle_btn.setToolTip("Toggle Description panel")
        self.toggle_btn.setAutoRaise(False)
        self.toggle_btn.setStyleSheet("""
            QToolButton {
                background-color: #F5F5F5;
                border: 1px solid #999999;
                border-radius: 4px;
                font-size: 16px;
                font-weight: bold;
                color: #333333;
            }
            QToolButton:hover {
                background-color: #E8E8E8;
                border: 1px solid #666666;
            }
            QToolButton:pressed {
                background-color: #D0D0D0;
            }
        """)
        self.toggle_btn.clicked.connect(self.toggle_callback)
        self._update_button_icon()
        
        layout.addStretch()
        layout.addWidget(self.toggle_btn)
        layout.addStretch()
    
    def set_description_visible(self, visible: bool) -> None:
        """Description 영역 표시 상태 업데이트"""
        self._desc_visible = visible
        self._update_button_icon()
    
    def _update_button_icon(self) -> None:
        """버튼 아이콘 업데이트 (← 또는 →)"""
        if self._desc_visible:
            # Description이 보이면 ← (숨기기)
            self.toggle_btn.setText("◀")
        else:
            # Description이 숨겨지면 → (보이기)
            self.toggle_btn.setText("▶")
    
    def sizeHint(self) -> QSize:
        """핸들 크기 - 더 넓게 설정하여 구분이 잘 되도록"""
        return QSize(10, 0) if self.orientation() == Qt.Horizontal else QSize(0, 10)


class DescriptionToggleSplitter(QSplitter):
    """Description 토글 버튼이 있는 커스텀 Splitter"""
    
    def __init__(self, orientation: Qt.Orientation, parent: QWidget = None, toggle_callback=None) -> None:
        super().__init__(orientation, parent)
        self.toggle_callback = toggle_callback
        self._handle: Optional[DescriptionToggleSplitterHandle] = None
    
    def createHandle(self) -> QSplitterHandle:
        """커스텀 핸들 생성"""
        handle = DescriptionToggleSplitterHandle(self.orientation(), self, self.toggle_callback)
        self._handle = handle
        return handle
    
    def set_description_visible(self, visible: bool) -> None:
        """Description 영역 표시 상태 업데이트"""
        # 핸들이 아직 생성되지 않았다면 모든 핸들을 확인
        if not self._handle:
            for i in range(self.count() - 1):
                try:
                    handle = self.handle(i + 1)
                    if isinstance(handle, DescriptionToggleSplitterHandle):
                        self._handle = handle
                        break
                except:
                    pass
        if self._handle:
            self._handle.set_description_visible(visible)
        else:
            # 핸들을 찾지 못한 경우, 모든 자식 위젯을 확인
            for child in self.findChildren(DescriptionToggleSplitterHandle):
                self._handle = child
                child.set_description_visible(visible)
                break


# ---------------------------
# Main Window
# ---------------------------
class MainWindow(QMainWindow):
    CATEGORY_ID_ROLE = Qt.UserRole + 201
    ITEM_ID_ROLE = Qt.UserRole + 202
    NODE_TYPE_ROLE = Qt.UserRole + 203  # "category" or "item"

    TRACE_MAX_LINES = 1200

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1460, 960)

        self.db = NoteDB(DEFAULT_DB_PATH)

        self.current_category_id: str = ""
        self.current_item_id: str = ""
        self.current_page_index: int = 0
        self._loading_ui: bool = False
        self._adjusting_splitter: bool = False  # Description 토글 중 splitter 크기 조정 플래그

        self._active_rich_edit: Optional[QTextEdit] = None
        self._desc_visible: bool = bool(self.db.ui_state.get("desc_visible", True))
        self._page_split_prev_sizes: Optional[List[int]] = None
        self._notes_split_prev_sizes: Optional[List[int]] = None

        self.viewer_a: Optional[ZoomPanAnnotateView] = None
        self.viewer_b: Optional[ZoomPanAnnotateView] = None
        self._active_pane: str = "A"

        self._trace_visible: bool = bool(self.db.ui_state.get("trace_visible", True))
        self._right_vsplit_prev_sizes: Optional[List[int]] = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_page_fields_to_model_and_save)

        self._last_save_warn_ts: float = 0.0
        self._save_warn_cooldown_sec: float = 10.0

        self._pane_ui: Dict[str, Dict[str, Any]] = {}

        self._build_ui()
        self._build_pane_overlays()

        self.page_splitter.splitterMoved.connect(self._on_page_splitter_moved)
        self.notes_ideas_splitter.splitterMoved.connect(self._on_notes_splitter_moved)
        self.right_vsplit.splitterMoved.connect(self._on_right_vsplit_moved)

        self._load_ui_state_or_defaults()
        self._apply_splitter_sizes_from_state()
        # 초기 Description 영역 표시 상태 설정
        # text_container는 항상 보이게 유지 (splitter 핸들이 보이도록)
        # 초기 크기 설정은 _set_desc_visible에서 처리
        if not self._desc_visible:
            # Description이 숨겨진 상태라면 최소 크기로 설정
            QTimer.singleShot(50, lambda: self._set_desc_visible(False, persist=False))
        # 상단 토글 버튼 초기 상태 설정
        if hasattr(self, 'btn_toggle_desc'):
            self._update_desc_toggle_button_text()
        # Splitter 핸들 초기 상태 설정 (위젯 추가 후 핸들이 생성되므로 지연 처리)
        QTimer.singleShot(100, lambda: self._update_splitter_handle_state())
        self._refresh_nav_tree(select_current=True)

        # 시작 상태가 Folder라면 placeholder(빈 캔버스)로
        if self.current_item_id:
            self._show_placeholder(False)
            self._load_current_item_page_to_ui()
        else:
            self._show_placeholder(True)
            self._load_current_item_page_to_ui(clear_only=True)

        self._load_global_ideas_to_ui()

        ideas_vis = bool(self.db.ui_state.get("global_ideas_visible", False))
        self._set_global_ideas_visible(ideas_vis, persist=False)
        self._set_desc_visible(bool(self.db.ui_state.get("desc_visible", True)), persist=False)
        self._set_trace_visible(self._trace_visible, persist=False)

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
        self.trace("App initialized", "INFO")

    # ---------------- placeholder (Folder 선택 시 우측을 '빈 캔버스'로) ----------------
    def _show_placeholder(self, show: bool) -> None:
        # content_stack:
        #   0 = editor(Chart/Description 포함)
        #   1 = placeholder(Select an item to view 만)
        self.content_stack.setCurrentIndex(1 if show else 0)

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

    def _remember_right_vsplit_sizes(self) -> None:
        try:
            sizes = self.right_vsplit.sizes()
            if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(x, int) for x in sizes):
                if sizes[0] >= 0 and sizes[1] >= 0:
                    self._right_vsplit_prev_sizes = list(sizes)
                    self.db.ui_state["right_vsplit_sizes"] = list(sizes)
        except Exception:
            pass

    def _apply_right_vsplit_sizes(self) -> None:
        v = self.db.ui_state.get("right_vsplit_sizes")
        if isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v):
            if v[0] >= 0 and v[1] >= 0:
                try:
                    self._right_vsplit_prev_sizes = list(v)
                    self.right_vsplit.setSizes(v)
                except Exception:
                    pass

    def _set_trace_visible(self, visible: bool, persist: bool = True) -> None:
        self._trace_visible = bool(visible)
        self.trace_group.setVisible(self._trace_visible)
        self.trace_show_row.setVisible(not self._trace_visible)

        try:
            total = max(1, self.right_vsplit.height())
            if self._trace_visible:
                self._apply_right_vsplit_sizes()
                if not self._right_vsplit_prev_sizes:
                    trace_h = 210
                    self.right_vsplit.setSizes([max(1, total - trace_h), trace_h])
            else:
                self._remember_right_vsplit_sizes()
                self.right_vsplit.setSizes([max(1, total - 38), 38])
        except Exception:
            pass

        if persist:
            self.db.ui_state["trace_visible"] = bool(self._trace_visible)
            self._save_db_with_warning()

    def _on_right_vsplit_moved(self, pos: int, index: int) -> None:
        if self._loading_ui:
            return
        if not self._trace_visible:
            return
        self._remember_right_vsplit_sizes()
        self._save_db_with_warning()

    def _post_init_layout_fix(self) -> None:
        try:
            self._apply_splitter_sizes_from_state()
            self._update_text_area_layout()
            for pane in ("A", "B"):
                self._reposition_overlay(pane)
            if self._trace_visible:
                self._apply_right_vsplit_sizes()
            self.trace("Post-init layout fix applied", "DEBUG")
        except Exception as e:
            self.trace(f"Post-init layout fix failed: {e}", "WARN")

    def closeEvent(self, event) -> None:
        try:
            self._remember_right_vsplit_sizes()
            self._flush_page_fields_to_model_and_save()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- Splitter persistence helpers ----------------
    def _is_valid_splitter_sizes(self, v: Any) -> bool:
        return isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v) and v[0] >= 0 and v[1] >= 0

    def _is_valid_notes_sizes_for_both_visible(self, v: Any) -> bool:
        if not self._is_valid_splitter_sizes(v):
            return False
        left, right = int(v[0]), int(v[1])
        return not (right < 120 or left < 120)

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
        # Description 토글 중에는 크기 저장하지 않음
        if self._adjusting_splitter:
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

            self._apply_right_vsplit_sizes()
        finally:
            self._loading_ui = False

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)

        main_splitter = QSplitter(Qt.Horizontal, root)

        # Left: tree + controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        ctrl = QWidget()
        ctrl_l = QHBoxLayout(ctrl)
        ctrl_l.setContentsMargins(0, 0, 0, 0)
        ctrl_l.setSpacing(4)

        # 간단한 아이콘 버튼들만 표시
        self.btn_add_folder = QToolButton()
        self.btn_add_folder.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.btn_add_folder.setToolTip("Add Folder")
        self.btn_add_folder.setFixedSize(32, 32)
        
        self.btn_add_item = QToolButton()
        self.btn_add_item.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        self.btn_add_item.setToolTip("Add Item")
        self.btn_add_item.setFixedSize(32, 32)
        
        self.btn_move_up = QToolButton()
        self.btn_move_up.setText("↑")
        self.btn_move_up.setToolTip("Move Up")
        self.btn_move_up.setFixedSize(32, 32)
        
        self.btn_move_down = QToolButton()
        self.btn_move_down.setText("↓")
        self.btn_move_down.setToolTip("Move Down")
        self.btn_move_down.setFixedSize(32, 32)

        # 내부적으로 사용할 버튼들 (컨텍스트 메뉴에서만 사용)
        self.btn_rename_folder = QToolButton()
        self.btn_del_folder = QToolButton()
        self.btn_rename_item = QToolButton()
        self.btn_del_item = QToolButton()
        self.btn_folder_up = QToolButton()
        self.btn_folder_down = QToolButton()
        self.btn_item_up = QToolButton()
        self.btn_item_down = QToolButton()

        ctrl_l.addWidget(self.btn_add_folder)
        ctrl_l.addWidget(self.btn_add_item)
        ctrl_l.addWidget(self.btn_move_up)
        ctrl_l.addWidget(self.btn_move_down)
        ctrl_l.addStretch()

        self.btn_add_folder.clicked.connect(self.add_folder)
        self.btn_add_item.clicked.connect(self.add_item)
        self.btn_move_up.clicked.connect(self._move_current_up)
        self.btn_move_down.clicked.connect(self._move_current_down)

        self.nav_tree = QTreeWidget()
        self.nav_tree.setHeaderHidden(True)
        self.nav_tree.setUniformRowHeights(True)
        self.nav_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.nav_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.nav_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.nav_tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        
        # 트리 아이템 확장/축소 시 아이콘 업데이트
        self.nav_tree.itemExpanded.connect(self._on_tree_item_expanded)
        self.nav_tree.itemCollapsed.connect(self._on_tree_item_collapsed)
        
        # ttk 스타일처럼 기본 확장 아이콘 숨기기 (커스텀 + 아이콘만 사용)
        self.nav_tree.setStyleSheet("""
            QTreeWidget::branch {
                background: transparent;
                border: none;
            }
            QTreeWidget::branch:has-siblings:!adjoins-item {
                border-image: none;
                border: none;
            }
            QTreeWidget::branch:has-siblings:adjoins-item {
                border-image: none;
                border: none;
            }
            QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
                border-image: none;
                border: none;
            }
            QTreeWidget::branch:has-children:!expanded:adjoins-item {
                border-image: none;
                border: none;
                image: none;
            }
            QTreeWidget::branch:expanded:adjoins-item {
                border-image: none;
                border: none;
                image: none;
            }
        """)

        left_layout.addWidget(ctrl)
        left_layout.addWidget(self.nav_tree, 1)

        # Right panel: vertical split (top content + bottom trace)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.right_vsplit = QSplitter(Qt.Vertical)
        self.right_vsplit.setChildrenCollapsible(False)

        # ---- top area (content_stack) ----
        main_content = QWidget()
        main_content_l = QVBoxLayout(main_content)
        main_content_l.setContentsMargins(0, 0, 0, 0)
        main_content_l.setSpacing(8)

        # 핵심: content_stack으로 "editor 전체" vs "빈 캔버스 안내"를 전환
        self.content_stack = QStackedWidget()
        self.content_stack.setContentsMargins(0, 0, 0, 0)

        # editor (page_splitter)
        self.page_splitter = DescriptionToggleSplitter(Qt.Horizontal, toggle_callback=self._on_toggle_desc_clicked)

        # -------- Images (A/B vertical) --------
        self.img_container = QWidget()
        img_layout = QVBoxLayout(self.img_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(6)

        meta_widget = QWidget()
        meta_flow = FlowLayout(meta_widget, margin=0, spacing=6)
        
        lbl_name = QLabel("Name:")
        lbl_name.setFixedHeight(26)
        lbl_name.setAlignment(Qt.AlignVCenter)
        meta_flow.addWidget(lbl_name)
        
        self.edit_stock_name = QLineEdit()
        self.edit_stock_name.setFixedSize(220, 26)
        self.edit_stock_name.textChanged.connect(self._on_page_field_changed)
        meta_flow.addWidget(self.edit_stock_name)
        
        lbl_ticker = QLabel("Ticker:")
        lbl_ticker.setFixedHeight(26)
        lbl_ticker.setAlignment(Qt.AlignVCenter)
        meta_flow.addWidget(lbl_ticker)
        
        self.edit_ticker = QLineEdit()
        self.edit_ticker.setFixedSize(120, 26)
        self.edit_ticker.textChanged.connect(self._on_page_field_changed)
        meta_flow.addWidget(self.edit_ticker)
        
        self.btn_copy_ticker = QToolButton()
        self.btn_copy_ticker.setIcon(_make_copy_icon(16))
        self.btn_copy_ticker.setToolTip("Copy ticker to clipboard")
        self.btn_copy_ticker.setFixedSize(30, 26)
        self.btn_copy_ticker.clicked.connect(self.copy_ticker)
        meta_flow.addWidget(self.btn_copy_ticker)
        
        # Description 토글 버튼 추가
        self.btn_toggle_desc = QToolButton()
        self.btn_toggle_desc.setCheckable(True)
        self.btn_toggle_desc.setChecked(self._desc_visible)
        self.btn_toggle_desc.setToolTip("Show/Hide Description panel")
        self.btn_toggle_desc.setFixedSize(80, 26)
        self.btn_toggle_desc.toggled.connect(self._on_toggle_desc)
        self._update_desc_toggle_button_text()
        meta_flow.addWidget(self.btn_toggle_desc)
        
        img_layout.addWidget(meta_widget)

        self.dual_view_splitter = QSplitter(Qt.Vertical)
        self.dual_view_splitter.setChildrenCollapsible(False)

        # Pane A
        paneA = QWidget()
        paneA_l = QVBoxLayout(paneA)
        paneA_l.setContentsMargins(0, 0, 0, 0)
        paneA_l.setSpacing(6)

        barA = QWidget()
        barA_l = QHBoxLayout(barA)
        barA_l.setContentsMargins(0, 0, 0, 0)
        barA_l.setSpacing(4)
        
        lblA = QLabel("Chart A")
        lblA.setStyleSheet("font-weight: 700; font-size: 11pt;")
        barA_l.addWidget(lblA)
        
        # 아이콘 버튼들
        self.btn_open_a = QToolButton()
        self.btn_open_a.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.btn_open_a.setToolTip("Open Image (A)")
        self.btn_open_a.setFixedSize(28, 28)
        self.btn_open_a.clicked.connect(lambda: self.set_image_via_dialog("A"))
        
        self.btn_paste_a = QToolButton()
        # 클립보드 아이콘이 없으면 텍스트로 표시
        paste_icon = self.style().standardIcon(QStyle.SP_FileDialogContentsView)
        if paste_icon.isNull():
            self.btn_paste_a.setText("📋")
        else:
            self.btn_paste_a.setIcon(paste_icon)
        self.btn_paste_a.setToolTip("Paste from Clipboard (A)")
        self.btn_paste_a.setFixedSize(28, 28)
        self.btn_paste_a.clicked.connect(lambda: self.paste_image_from_clipboard("A"))
        
        # 드롭다운 메뉴 버튼 (Clear, Fit 포함)
        self.btn_menu_a = QToolButton()
        self.btn_menu_a.setText("⋯")
        self.btn_menu_a.setToolTip("More options (A)")
        self.btn_menu_a.setFixedSize(28, 28)
        menu_a = QMenu(self)
        menu_a.addAction("Clear Image", lambda: self.clear_image("A"))
        menu_a.addAction("Fit to View", lambda: self.reset_image_view("A"))
        self.btn_menu_a.setMenu(menu_a)
        self.btn_menu_a.setPopupMode(QToolButton.InstantPopup)
        
        barA_l.addWidget(self.btn_open_a)
        barA_l.addWidget(self.btn_paste_a)
        barA_l.addWidget(self.btn_menu_a)
        barA_l.addStretch()
        
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
        barB_l = QHBoxLayout(barB)
        barB_l.setContentsMargins(0, 0, 0, 0)
        barB_l.setSpacing(4)
        
        lblB = QLabel("Chart B")
        lblB.setStyleSheet("font-weight: 700; font-size: 11pt;")
        barB_l.addWidget(lblB)
        
        # 아이콘 버튼들
        self.btn_open_b = QToolButton()
        self.btn_open_b.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.btn_open_b.setToolTip("Open Image (B)")
        self.btn_open_b.setFixedSize(28, 28)
        self.btn_open_b.clicked.connect(lambda: self.set_image_via_dialog("B"))
        
        self.btn_paste_b = QToolButton()
        # 클립보드 아이콘이 없으면 텍스트로 표시
        paste_icon = self.style().standardIcon(QStyle.SP_FileDialogContentsView)
        if paste_icon.isNull():
            self.btn_paste_b.setText("📋")
        else:
            self.btn_paste_b.setIcon(paste_icon)
        self.btn_paste_b.setToolTip("Paste from Clipboard (B)")
        self.btn_paste_b.setFixedSize(28, 28)
        self.btn_paste_b.clicked.connect(lambda: self.paste_image_from_clipboard("B"))
        
        # 드롭다운 메뉴 버튼 (Clear, Fit 포함)
        self.btn_menu_b = QToolButton()
        self.btn_menu_b.setText("⋯")
        self.btn_menu_b.setToolTip("More options (B)")
        self.btn_menu_b.setFixedSize(28, 28)
        menu_b = QMenu(self)
        menu_b.addAction("Clear Image", lambda: self.clear_image("B"))
        menu_b.addAction("Fit to View", lambda: self.reset_image_view("B"))
        self.btn_menu_b.setMenu(menu_b)
        self.btn_menu_b.setPopupMode(QToolButton.InstantPopup)
        
        barB_l.addWidget(self.btn_open_b)
        barB_l.addWidget(self.btn_paste_b)
        barB_l.addWidget(self.btn_menu_b)
        barB_l.addStretch()
        
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

        nav_widget = QWidget()
        nav_flow = FlowLayout(nav_widget, margin=0, spacing=6)
        self.btn_prev = QToolButton(); self.btn_prev.setText("◀"); self.btn_prev.clicked.connect(self.go_prev_page)
        self.lbl_page = QLabel("0 / 0"); self.lbl_page.setAlignment(Qt.AlignCenter); self.lbl_page.setMinimumWidth(80)
        self.btn_next = QToolButton(); self.btn_next.setText("▶"); self.btn_next.clicked.connect(self.go_next_page)
        self.btn_add_page = QToolButton(); self.btn_add_page.setText("+ Page"); self.btn_add_page.clicked.connect(self.add_page)
        self.btn_del_page = QToolButton(); self.btn_del_page.setText("Del Page"); self.btn_del_page.clicked.connect(self.delete_page)
        for w in [self.btn_prev, self.lbl_page, self.btn_next, self.btn_add_page, self.btn_del_page]:
            nav_flow.addWidget(w)
        img_layout.addWidget(nav_widget)

        # -------- Text (Description + checklist + ideas) --------
        self.text_container = QWidget()
        text_layout = QVBoxLayout(self.text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        def _vsep() -> QFrame:
            v = QFrame()
            v.setFrameShape(QFrame.VLine)
            v.setFrameShadow(QFrame.Sunken)
            v.setStyleSheet("color: #CFCFCF;")
            v.setFixedHeight(22)
            return v

        self.fmt_row = QWidget()
        fmt_outer = QVBoxLayout(self.fmt_row)
        fmt_outer.setContentsMargins(0, 0, 0, 0)
        fmt_outer.setSpacing(4)

        self.btn_fmt_bold = QToolButton(); self.btn_fmt_bold.setText("B"); self.btn_fmt_bold.setCheckable(True); self.btn_fmt_bold.setFixedSize(28, 26)
        self.btn_fmt_bold.setStyleSheet("font-weight: 800;"); self.btn_fmt_bold.setToolTip("Bold (Ctrl+B)")
        self.btn_fmt_italic = QToolButton(); self.btn_fmt_italic.setText("I"); self.btn_fmt_italic.setCheckable(True); self.btn_fmt_italic.setFixedSize(28, 26)
        self.btn_fmt_italic.setStyleSheet("font-style: italic; font-weight: 600;"); self.btn_fmt_italic.setToolTip("Italic (Ctrl+I)")
        self.btn_fmt_underline = QToolButton(); self.btn_fmt_underline.setText("U"); self.btn_fmt_underline.setCheckable(True); self.btn_fmt_underline.setFixedSize(28, 26)
        self.btn_fmt_underline.setStyleSheet("text-decoration: underline; font-weight: 600;"); self.btn_fmt_underline.setToolTip("Underline (Ctrl+U)")

        self.btn_fmt_bold.toggled.connect(lambda v: self._apply_format(bold=v))
        self.btn_fmt_italic.toggled.connect(lambda v: self._apply_format(italic=v))
        self.btn_fmt_underline.toggled.connect(lambda v: self._apply_format(underline=v))

        self._color_group = QButtonGroup(self); self._color_group.setExclusive(True)

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

        for idx, btn in enumerate([self.btn_col_default, self.btn_col_red, self.btn_col_blue, self.btn_col_yellow]):
            self._color_group.addButton(btn, idx)

        self.btn_col_default.toggled.connect(lambda v: v and self._apply_text_color(COLOR_DEFAULT))
        self.btn_col_red.toggled.connect(lambda v: v and self._apply_text_color(COLOR_RED))
        self.btn_col_blue.toggled.connect(lambda v: v and self._apply_text_color(COLOR_BLUE))
        self.btn_col_yellow.toggled.connect(lambda v: v and self._apply_text_color(COLOR_YELLOW))

        self.btn_bullets = QToolButton(); self.btn_bullets.setText("•"); self.btn_bullets.setFixedSize(28, 26); self.btn_bullets.setToolTip("Bulleted List")
        self.btn_numbered = QToolButton(); self.btn_numbered.setText("1."); self.btn_numbered.setFixedSize(32, 26); self.btn_numbered.setToolTip("Numbered List")
        self.btn_bullets.clicked.connect(lambda: self._apply_list("bullet"))
        self.btn_numbered.clicked.connect(lambda: self._apply_list("number"))

        self.btn_ideas = QToolButton(); self.btn_ideas.setText("Ideas"); self.btn_ideas.setCheckable(True)
        self.btn_ideas.setToolTip("Toggle Global Ideas panel (전역 아이디어)")
        self.btn_ideas.toggled.connect(self._on_toggle_ideas)

        row1 = QWidget(); r1 = QHBoxLayout(row1); r1.setContentsMargins(0,0,0,0); r1.setSpacing(6)
        self.text_title = QLabel("Description / Notes"); self.text_title.setStyleSheet("font-weight: 600;")
        r1.addWidget(self.text_title)
        r1.addWidget(_vsep())
        r1.addWidget(self.btn_fmt_bold)
        r1.addWidget(self.btn_fmt_italic)
        r1.addWidget(self.btn_fmt_underline)
        r1.addStretch(1)
        r1.addWidget(self.btn_ideas)

        row2 = QWidget(); r2 = QHBoxLayout(row2); r2.setContentsMargins(0,0,0,0); r2.setSpacing(6)
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
        notes_left_l.setContentsMargins(0,0,0,0)
        notes_left_l.setSpacing(6)

        self.chk_group = QGroupBox("Checklist")
        chk_layout = QVBoxLayout(self.chk_group)
        chk_layout.setContentsMargins(10,10,10,10)
        chk_layout.setSpacing(6)

        self.chk_boxes: List[QCheckBox] = []
        self.chk_notes: List[QTextEdit] = []
        for q in DEFAULT_CHECK_QUESTIONS:
            cb = QCheckBox(q); cb.stateChanged.connect(self._on_page_field_changed)
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
        ideas_l.setContentsMargins(10,10,10,10)
        ideas_l.setSpacing(6)
        self.lbl_ideas = QLabel("Global Ideas"); self.lbl_ideas.setStyleSheet("font-weight: 700;")
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

        text_layout.addWidget(self.fmt_row)
        text_layout.addWidget(self.notes_ideas_splitter, 1)

        self.page_splitter.addWidget(self.img_container)
        self.page_splitter.addWidget(self.text_container)
        # 초기 stretch factor 설정 (Chart와 Description 모두 보이도록)
        self.page_splitter.setStretchFactor(0, 1)  # Chart
        self.page_splitter.setStretchFactor(1, 1)  # Description
        self.text_container.setMinimumWidth(440)

        self._set_active_rich_edit(self.text_edit)
        self.btn_col_default.setChecked(True)

        # ---------- Placeholder widget (Folder 선택 시 "빈 캔버스 + 안내 문구") ----------
        placeholder = QWidget()
        placeholder.setStyleSheet("QWidget { background: #FFFFFF; }")
        ph_l = QVBoxLayout(placeholder)
        ph_l.setContentsMargins(0, 0, 0, 0)
        ph_l.setSpacing(0)
        ph_l.addStretch(1)
        lbl = QLabel("Select an item to view")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #444;")
        ph_l.addWidget(lbl)
        ph_l.addSpacing(10)
        sub = QLabel("Folder has no contents.\nChoose an Item in the left tree.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("font-size: 12px; color: #777;")
        ph_l.addWidget(sub)
        ph_l.addStretch(1)

        # content_stack: 0=editor, 1=placeholder
        self.content_stack.addWidget(self.page_splitter)
        self.content_stack.addWidget(placeholder)

        main_content_l.addWidget(self.content_stack, 1)

        # ---- Trace area (always available; visibility toggle supported) ----
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

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([420, 1040])

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

    # ---- 이하 기능 메서드들은 기존대로 동작 (선택 변경 시 placeholder 전환 포함) ----
    # NOTE: 아래 메서드들은 길어서 생략하면 실행이 불가하므로, 완전 통합본을 유지합니다.
    # (이하 코드는 이전 통합본과 동일하며, Folder 선택 시 _show_placeholder(True)를 강제하는 로직이 포함됩니다.)

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

        # Notes 버튼 제거 - 이제 splitter 핸들에 화살표 버튼 사용

        anno_panel = QFrame(vp)
        anno_panel.setFrameShape(QFrame.StyledPanel)
        anno_panel.setVisible(False)
        anno_panel.setFixedWidth(240)
        anno_panel.setStyleSheet("""
            QFrame { background: rgba(255,255,255,235); border: 1px solid #9A9A9A; border-radius: 10px; }
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
            viewer.set_mode_draw() if checked else viewer.set_mode_pan()
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
                self, "Clear Lines",
                f"Clear all annotation lines on Chart {pane}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
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

        def close_panel():
            if btn_draw_mode.isChecked():
                btn_draw_mode.setChecked(False)
                viewer.set_mode_pan()
            anno_panel.setVisible(False)
            btn_anno_toggle.setVisible(True)
            self._reposition_overlay(pane)

        btn_anno_toggle.clicked.connect(open_panel)
        btn_anno_close.clicked.connect(close_panel)

        self._reposition_overlay(pane)

        return {
            "viewer": viewer,
            "cap": edit_cap,
            "anno_toggle": btn_anno_toggle,
            # desc_toggle 제거됨 - splitter 핸들 버튼 사용
            "panel": anno_panel,
            "draw": btn_draw_mode,
        }

    def _set_active_pane(self, pane: str) -> None:
        pane = "A" if pane not in ("A", "B") else pane
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
        anno_panel: QFrame = ui["panel"]

        w = vp.width()
        margin = 10
        gap = 6

        if anno_panel.isVisible():
            panel_x = max(margin, w - anno_panel.width() - margin)
            anno_panel.move(panel_x, margin)
            btn_anno_toggle.move(max(margin, panel_x - margin - btn_anno_toggle.width()), margin)
        else:
            btn_anno_toggle.move(max(margin, w - btn_anno_toggle.width() - margin), margin)

        cap_min = 260
        cap_max = 720
        cap_right_limit = (anno_panel.x() - margin) if anno_panel.isVisible() else (btn_anno_toggle.x() - margin)
        cap_w = min(cap_max, max(cap_min, cap_right_limit - margin))
        cap_x = max(margin, cap_right_limit - cap_w)
        edit_cap.setFixedWidth(cap_w)
        edit_cap.move(cap_x, margin)

    # ---------------- Tree refresh ---------------- 
    def _refresh_nav_tree(self, select_current: bool = False) -> None:
        self.nav_tree.blockSignals(True)
        self.nav_tree.clear()
        
        # 표준 아이콘 준비
        file_icon = self.style().standardIcon(QStyle.SP_FileIcon)

        item_to_qitem: Dict[str, QTreeWidgetItem] = {}
        cat_to_qitem: Dict[str, QTreeWidgetItem] = {}

        def add_cat(cid: str, parent_q: Optional[QTreeWidgetItem]) -> Optional[QTreeWidgetItem]:
            c = self.db.get_category(cid)
            if not c:
                return None
            
            # 자식이 있으면 사각형 + 아이콘 사용
            has_children = bool(c.child_ids or c.item_ids)
            
            q = QTreeWidgetItem([c.name])
            q.setData(0, self.NODE_TYPE_ROLE, "category")
            q.setData(0, self.CATEGORY_ID_ROLE, c.id)
            q.setFlags(q.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            
            # 자식이 있으면 사각형 + 아이콘 설정
            if has_children:
                q.setIcon(0, _make_expand_icon(16, expanded=False))
            
            # ✅ Category(폴더)만 Bold
            f = q.font(0)
            f.setBold(True)
            q.setFont(0, f)
            
            if parent_q is None:
                self.nav_tree.addTopLevelItem(q)
            else:
                parent_q.addChild(q)
            cat_to_qitem[cid] = q

            for iid in c.item_ids:
                it = self.db.get_item(iid)
                if not it:
                    continue
                qi = QTreeWidgetItem([it.name])
                qi.setData(0, self.NODE_TYPE_ROLE, "item")
                qi.setData(0, self.ITEM_ID_ROLE, it.id)
                qi.setFlags(qi.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                
                # ✅ Item(File) icon
                qi.setIcon(0, file_icon)
                
                q.addChild(qi)
                item_to_qitem[it.id] = qi

            for ch in c.child_ids:
                add_cat(ch, q)
            return q

        for rid in self.db.root_category_ids:
            add_cat(rid, None)

        # 트리 아이템의 초기 확장 상태에 맞게 아이콘 설정
        def update_icons_recursive(item: QTreeWidgetItem):
            if item.childCount() > 0:
                item.setIcon(0, _make_expand_icon(16, expanded=item.isExpanded()))
            for i in range(item.childCount()):
                update_icons_recursive(item.child(i))
        
        for i in range(self.nav_tree.topLevelItemCount()):
            update_icons_recursive(self.nav_tree.topLevelItem(i))
        
        self.nav_tree.expandAll()
        
        # expandAll 후 다시 아이콘 업데이트
        for i in range(self.nav_tree.topLevelItemCount()):
            update_icons_recursive(self.nav_tree.topLevelItem(i))

        if select_current:
            if self.current_item_id and self.current_item_id in item_to_qitem:
                self.nav_tree.setCurrentItem(item_to_qitem[self.current_item_id])
            elif self.current_category_id and self.current_category_id in cat_to_qitem:
                self.nav_tree.setCurrentItem(cat_to_qitem[self.current_category_id])

        self.nav_tree.blockSignals(False)
        self._update_left_buttons_enabled()

    def _update_left_buttons_enabled(self) -> None:
        it = self.nav_tree.currentItem()
        node_type = it.data(0, self.NODE_TYPE_ROLE) if it else None
        is_cat = (node_type == "category")
        is_item = (node_type == "item")

        # 이동 버튼은 선택된 항목이 있을 때만 활성화
        self.btn_move_up.setEnabled(is_cat or is_item)
        self.btn_move_down.setEnabled(is_cat or is_item)

        # 내부 버튼들 (컨텍스트 메뉴용)
        self.btn_rename_folder.setEnabled(is_cat)
        self.btn_del_folder.setEnabled(is_cat)
        self.btn_folder_up.setEnabled(is_cat)
        self.btn_folder_down.setEnabled(is_cat)

        self.btn_rename_item.setEnabled(is_item)
        self.btn_del_item.setEnabled(is_item)
        self.btn_item_up.setEnabled(is_item)
        self.btn_item_down.setEnabled(is_item)

        self.btn_add_folder.setEnabled(True)
        self.btn_add_item.setEnabled(True)
    
    def _move_current_up(self) -> None:
        """현재 선택된 항목을 위로 이동"""
        it = self.nav_tree.currentItem()
        if not it:
            return
        node_type = it.data(0, self.NODE_TYPE_ROLE)
        if node_type == "category":
            self.move_folder(-1)
        elif node_type == "item":
            self.move_item(-1)
    
    def _move_current_down(self) -> None:
        """현재 선택된 항목을 아래로 이동"""
        it = self.nav_tree.currentItem()
        if not it:
            return
        node_type = it.data(0, self.NODE_TYPE_ROLE)
        if node_type == "category":
            self.move_folder(+1)
        elif node_type == "item":
            self.move_item(+1)

    def _on_tree_context_menu(self, pos) -> None:
        item = self.nav_tree.itemAt(pos)
        if not item:
            return
        node_type = item.data(0, self.NODE_TYPE_ROLE)

        menu = QMenu(self)
        if node_type == "category":
            act_add_folder = menu.addAction("+ Folder (sub)")
            act_add_item = menu.addAction("+ Item")
            menu.addSeparator()
            act_rename = menu.addAction("Rename Folder")
            act_delete = menu.addAction("Delete Folder")
            menu.addSeparator()
            act_up = menu.addAction("Move Folder Up")
            act_down = menu.addAction("Move Folder Down")
            chosen = menu.exec_(self.nav_tree.viewport().mapToGlobal(pos))
            if not chosen:
                return
            if chosen == act_add_folder:
                self.add_folder()
            elif chosen == act_add_item:
                self.add_item()
            elif chosen == act_rename:
                self.rename_folder()
            elif chosen == act_delete:
                self.delete_folder()
            elif chosen == act_up:
                self.move_folder(-1)
            elif chosen == act_down:
                self.move_folder(+1)
            return

        if node_type == "item":
            act_add_item = menu.addAction("+ Item (same folder)")
            menu.addSeparator()
            act_rename = menu.addAction("Rename Item")
            act_delete = menu.addAction("Delete Item")
            act_move_to_folder = menu.addAction("Move Item to Folder...")
            menu.addSeparator()
            act_up = menu.addAction("Move Item Up")
            act_down = menu.addAction("Move Item Down")
            chosen = menu.exec_(self.nav_tree.viewport().mapToGlobal(pos))
            if not chosen:
                return
            if chosen == act_add_item:
                self.add_item()
            elif chosen == act_rename:
                self.rename_item()
            elif chosen == act_delete:
                self.delete_item()
            elif chosen == act_move_to_folder:
                self.move_item_to_folder()
            elif chosen == act_up:
                self.move_item(-1)
            elif chosen == act_down:
                self.move_item(+1)
            return

    # ---------------- State helpers ----------------
    def _load_ui_state_or_defaults(self) -> None:
        cid = str(self.db.ui_state.get("selected_category_id", "") or "")
        iid = str(self.db.ui_state.get("selected_item_id", "") or "")
        page_idx = self.db.ui_state.get("current_page_index", 0)

        if cid and self.db.get_category(cid):
            self.current_category_id = cid
        else:
            self.current_category_id = self.db.root_category_ids[0] if self.db.root_category_ids else ""

        if iid and self.db.get_item(iid):
            self.current_item_id = iid
            found = self.db.find_item(iid)
            if found:
                self.current_category_id = found[1].id
        else:
            self.current_item_id = ""

        self.current_page_index = int(page_idx) if isinstance(page_idx, int) else 0
        it = self.current_item()
        if it and it.pages:
            self.current_page_index = max(0, min(self.current_page_index, len(it.pages) - 1))
        else:
            self.current_page_index = 0

    def current_item(self) -> Optional[Item]:
        return self.db.get_item(self.current_item_id) if self.current_item_id else None

    def current_page(self) -> Optional[Page]:
        it = self.current_item()
        if not it or not it.pages:
            return None
        idx = max(0, min(self.current_page_index, len(it.pages) - 1))
        return it.pages[idx]

    def _save_ui_state(self) -> None:
        self.db.ui_state["selected_category_id"] = self.current_category_id
        self.db.ui_state["selected_item_id"] = self.current_item_id
        self.db.ui_state["current_page_index"] = self.current_page_index
        self.db.ui_state["desc_visible"] = bool(self._desc_visible)
        self.db.ui_state["global_ideas_visible"] = bool(self.ideas_panel.isVisible())
        self.db.ui_state["trace_visible"] = bool(self._trace_visible)
        if self.text_container.isVisible():
            self._remember_page_splitter_sizes()
        if self.notes_left.isVisible() and self.ideas_panel.isVisible():
            self._remember_notes_splitter_sizes()
        self._remember_right_vsplit_sizes()

    # ---------------- Tree expand/collapse icon update ----------------
    def _on_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        """트리 아이템 확장 시 아이콘을 - 모양으로 변경"""
        if item.childCount() > 0:
            item.setIcon(0, _make_expand_icon(16, expanded=True))
    
    def _on_tree_item_collapsed(self, item: QTreeWidgetItem) -> None:
        """트리 아이템 축소 시 아이콘을 + 모양으로 변경"""
        if item.childCount() > 0:
            item.setIcon(0, _make_expand_icon(16, expanded=False))
    
    # ---------------- Selection changed ----------------
    def _on_tree_selection_changed(self) -> None:
        item = self.nav_tree.currentItem()
        if not item:
            return

        node_type = item.data(0, self.NODE_TYPE_ROLE)
        self._update_left_buttons_enabled()

        # Folder 선택: 우측 편집 영역 완전 숨김(placeholder로 전환)
        if node_type == "category":
            cid = str(item.data(0, self.CATEGORY_ID_ROLE) or "")
            self._flush_page_fields_to_model_and_save()
            self.current_category_id = cid
            self.current_item_id = ""
            self.current_page_index = 0
            self._save_ui_state()

            self._show_placeholder(True)  # 핵심
            self._load_current_item_page_to_ui(clear_only=True)  # 필드 정리
            self.trace(f"Selected folder: {item.text(0)}", "INFO")
            return

        # Item 선택: 편집 영역 표시
        if node_type == "item":
            iid = str(item.data(0, self.ITEM_ID_ROLE) or "")
            if not iid:
                return
            if iid == self.current_item_id:
                self._show_placeholder(False)
                return

            self._flush_page_fields_to_model_and_save()
            found = self.db.find_item(iid)
            if not found:
                return
            it, cat = found
            self.current_item_id = it.id
            self.current_category_id = cat.id
            self.current_page_index = max(0, min(it.last_page_index, len(it.pages) - 1))
            self._save_ui_state()

            self._show_placeholder(False)
            self._load_current_item_page_to_ui()
            self.trace(f"Selected item: {it.name}", "INFO")
            return

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

        if clear_only or (not it) or (not pg):
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
                self._set_active_rich_edit(self.text_edit)
                self._sync_format_buttons()
            finally:
                self._loading_ui = False
            return

        self._loading_ui = True
        try:
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
                self.chk_notes[i].setHtml(val) if _looks_like_html(val) else self.chk_notes[i].setPlainText(val)

            val_desc = _strip_highlight_html(pg.note_text or "")
            self.text_edit.setHtml(val_desc) if _looks_like_html(val_desc) else self.text_edit.setPlainText(val_desc)

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
        if not self.current_item_id:
            return
        self._save_timer.start(450)

    def _collect_checklist_from_ui(self) -> Checklist:
        out: Checklist = []
        for i, q in enumerate(DEFAULT_CHECK_QUESTIONS):
            out.append({"q": q, "checked": bool(self.chk_boxes[i].isChecked()), "note": _strip_highlight_html(self.chk_notes[i].toHtml())})
        return out

    def _flush_page_fields_to_model_and_save(self) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg or self._loading_ui:
            try:
                new_global = _strip_highlight_html(self.edit_global_ideas.toHtml())
                if self.db.global_ideas != new_global:
                    self.db.global_ideas = new_global
                    self._save_ui_state()
                    self._save_db_with_warning()
            except Exception:
                pass
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
            pg.image_a_caption = new_cap_a; changed = True
        if pg.image_b_caption != new_cap_b:
            pg.image_b_caption = new_cap_b; changed = True

        new_text = _strip_highlight_html(self.text_edit.toHtml())
        if pg.note_text != new_text:
            pg.note_text = new_text; changed = True

        new_name = self.edit_stock_name.text()
        if pg.stock_name != new_name:
            pg.stock_name = new_name; changed = True

        new_ticker = self.edit_ticker.text()
        if pg.ticker != new_ticker:
            pg.ticker = new_ticker; changed = True

        if self.viewer_a is not None:
            new_strokes_a = self.viewer_a.get_strokes()
            if pg.strokes_a != new_strokes_a:
                pg.strokes_a = new_strokes_a; changed = True

        if self.viewer_b is not None:
            new_strokes_b = self.viewer_b.get_strokes()
            if pg.strokes_b != new_strokes_b:
                pg.strokes_b = new_strokes_b; changed = True

        new_checklist = self._collect_checklist_from_ui()
        if pg.checklist != new_checklist:
            pg.checklist = new_checklist; changed = True

        it.last_page_index = self.current_page_index
        self._save_ui_state()

        if changed:
            pg.updated_at = _now_epoch()

        self._save_db_with_warning()

    def force_save(self) -> None:
        self._flush_page_fields_to_model_and_save()
        QMessageBox.information(self, "Saved", "Save requested (check warnings if file is locked).")

    def _update_nav(self) -> None:
        it = self.current_item()
        total = len(it.pages) if it else 0
        cur = (self.current_page_index + 1) if total > 0 else 0
        self.lbl_page.setText(f"{cur} / {total}")
        self.btn_prev.setEnabled(total > 0 and self.current_page_index > 0)
        self.btn_next.setEnabled(total > 0 and self.current_page_index < total - 1)
        self.btn_del_page.setEnabled(total > 1)

    def _load_global_ideas_to_ui(self) -> None:
        self._loading_ui = True
        try:
            val = _strip_highlight_html(self.db.global_ideas or "")
            self.edit_global_ideas.setHtml(val) if _looks_like_html(val) else self.edit_global_ideas.setPlainText(val)
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

    def go_next_page(self) -> None:
        it = self.current_item()
        if not it or self.current_page_index >= len(it.pages) - 1:
            return
        self._flush_page_fields_to_model_and_save()
        self.current_page_index += 1
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._load_current_item_page_to_ui()

    def add_page(self) -> None:
        it = self.current_item()
        if not it:
            return
        self._flush_page_fields_to_model_and_save()
        insert_at = self.current_page_index + 1
        it.pages.insert(insert_at, self.db.new_page())
        self.current_page_index = insert_at
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._save_db_with_warning()
        self._load_current_item_page_to_ui()

    def delete_page(self) -> None:
        it = self.current_item()
        if not it or len(it.pages) <= 1:
            return
        reply = QMessageBox.question(self, "Delete Page", "Delete current page?\n(This cannot be undone.)",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._flush_page_fields_to_model_and_save()
        del it.pages[self.current_page_index]
        self.current_page_index = max(0, min(self.current_page_index, len(it.pages) - 1))
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._save_db_with_warning()
        self._load_current_item_page_to_ui()

    # ---------------- Image handling ----------------
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
        if not self.current_item_id:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select Chart Image ({pane})", "",
                                                   "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*.*)")
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
            pg.image_a_path = ""; pg.strokes_a = []; pg.image_a_caption = ""
            if self._pane_ui.get("A"): self._pane_ui["A"]["cap"].setPlainText("")
        else:
            pg.image_b_path = ""; pg.strokes_b = []; pg.image_b_caption = ""
            if self._pane_ui.get("B"): self._pane_ui["B"]["cap"].setPlainText("")
        pg.updated_at = _now_epoch()
        self._save_db_with_warning()
        viewer.clear_image()

    def paste_image_from_clipboard(self, pane: str) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg:
            return
        viewer = self.viewer_a if pane == "A" else self.viewer_b
        if viewer is None:
            return
        self._set_active_pane(pane)
        img: QImage = QApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, "Paste Image", "Clipboard does not contain an image.")
            return
        self._flush_page_fields_to_model_and_save()
        # 아이템 ID를 포함하여 고유한 폴더명 생성 (같은 이름의 아이템이 다른 폴더에 있어도 충돌 방지)
        safe_item = _sanitize_for_folder(f"{it.name}_{it.id[:8]}", it.id[:8])
        dst_dir = os.path.join(ASSETS_DIR, safe_item)
        _ensure_dir(dst_dir)
        dst_name = f"{pg.id}_{pane.lower()}_clip_{_now_epoch()}.png"
        dst_rel = _relpath_norm(os.path.join(dst_dir, dst_name))
        dst_abs = _abspath_from_rel(dst_rel)
        if not img.save(dst_abs, "PNG"):
            QMessageBox.warning(self, "Paste failed", "Clipboard image could not be saved as PNG.")
            return
        if pane == "A":
            pg.image_a_path = dst_rel; pg.strokes_a = []
        else:
            pg.image_b_path = dst_rel; pg.strokes_b = []
        pg.updated_at = _now_epoch()
        it.last_page_index = self.current_page_index
        self._save_ui_state()
        self._save_db_with_warning()
        viewer.set_image_path(dst_abs)
        viewer.set_strokes([])
        viewer.setFocus(Qt.MouseFocusReason)

    def _set_image_from_file(self, pane: str, src_path: str) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg or not os.path.isfile(src_path):
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
        # 아이템 ID를 포함하여 고유한 폴더명 생성 (같은 이름의 아이템이 다른 폴더에 있어도 충돌 방지)
        safe_item = _sanitize_for_folder(f"{it.name}_{it.id[:8]}", it.id[:8])
        dst_dir = os.path.join(ASSETS_DIR, safe_item)
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
            pg.image_a_path = dst_rel; pg.strokes_a = []
        else:
            pg.image_b_path = dst_rel; pg.strokes_b = []
        pg.updated_at = _now_epoch()
        it.last_page_index = self.current_page_index
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

    # ---------------- Folder / Item operations ----------------
    def _target_category_for_new(self) -> str:
        it = self.nav_tree.currentItem()
        if it:
            ntype = it.data(0, self.NODE_TYPE_ROLE)
            if ntype == "category":
                cid = str(it.data(0, self.CATEGORY_ID_ROLE) or "")
                if cid and self.db.get_category(cid):
                    return cid
            if ntype == "item":
                iid = str(it.data(0, self.ITEM_ID_ROLE) or "")
                found = self.db.find_item(iid)
                if found:
                    return found[1].id
        return self.db.root_category_ids[0] if self.db.root_category_ids else ""

    def add_folder(self) -> None:
        self._flush_page_fields_to_model_and_save()
        parent_cid = self._target_category_for_new()
        name, ok = QInputDialog.getText(self, "Add Folder", "Folder name:", text="New Folder")
        if not ok or not (name or "").strip():
            return
        c = self.db.add_category(name.strip(), parent_id=parent_cid if parent_cid else None)
        self.current_category_id = c.id
        self.current_item_id = ""
        self.current_page_index = 0
        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)
        self._show_placeholder(True)
        self._load_current_item_page_to_ui(clear_only=True)

    def rename_folder(self) -> None:
        it = self.nav_tree.currentItem()
        if not it or it.data(0, self.NODE_TYPE_ROLE) != "category":
            return
        cid = str(it.data(0, self.CATEGORY_ID_ROLE) or "")
        c = self.db.get_category(cid)
        if not c:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Folder", "New name:", text=c.name)
        if not ok or not (new_name or "").strip():
            return
        self.db.rename_category(cid, new_name.strip())
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)

    def delete_folder(self) -> None:
        it = self.nav_tree.currentItem()
        if not it or it.data(0, self.NODE_TYPE_ROLE) != "category":
            return
        cid = str(it.data(0, self.CATEGORY_ID_ROLE) or "")
        c = self.db.get_category(cid)
        if not c:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Folder")
        msg.setText(f"Folder '{c.name}' 처리 방식을 선택하세요.")
        btn_move = msg.addButton("Move contents to parent & delete folder", QMessageBox.ActionRole)
        btn_delete = msg.addButton("Delete folder and ALL contents", QMessageBox.DestructiveRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_cancel)
        msg.exec_()
        clicked = msg.clickedButton()
        if clicked == btn_cancel:
            return

        self._flush_page_fields_to_model_and_save()
        ok = False
        if clicked == btn_move:
            ok = self.db.delete_category_move_to_parent(cid)
        elif clicked == btn_delete:
            ok = self.db.delete_category_recursive(cid)
            if not ok:
                QMessageBox.warning(self, "Not allowed", "이 삭제는 모든 Item을 제거하게 되어 허용되지 않습니다.")
                return
        if not ok:
            return

        self.current_item_id = ""
        self.current_category_id = self.db.root_category_ids[0] if self.db.root_category_ids else ""
        self.current_page_index = 0
        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)
        self._show_placeholder(True)
        self._load_current_item_page_to_ui(clear_only=True)

    def move_folder(self, direction: int) -> None:
        it = self.nav_tree.currentItem()
        if not it or it.data(0, self.NODE_TYPE_ROLE) != "category":
            return
        cid = str(it.data(0, self.CATEGORY_ID_ROLE) or "")
        if not cid:
            return
        self.db.move_category_sibling(cid, direction)
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)

    def add_item(self) -> None:
        self._flush_page_fields_to_model_and_save()
        cid = self._target_category_for_new()
        if not cid:
            return
        name, ok = QInputDialog.getText(self, "Add Item", "Item name (in folder):", text="New Item")
        if not ok or not (name or "").strip():
            return
        it = self.db.add_item(name.strip(), cid)
        self.current_category_id = cid
        self.current_item_id = it.id
        self.current_page_index = 0
        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)
        self._show_placeholder(False)
        self._load_current_item_page_to_ui()

    def rename_item(self) -> None:
        itw = self.nav_tree.currentItem()
        if not itw or itw.data(0, self.NODE_TYPE_ROLE) != "item":
            return
        iid = str(itw.data(0, self.ITEM_ID_ROLE) or "")
        it = self.db.get_item(iid)
        if not it:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Item", "New name:", text=it.name)
        if not ok or not (new_name or "").strip():
            return
        self.db.rename_item(iid, new_name.strip())
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)

    def delete_item(self) -> None:
        itw = self.nav_tree.currentItem()
        if not itw or itw.data(0, self.NODE_TYPE_ROLE) != "item":
            return
        iid = str(itw.data(0, self.ITEM_ID_ROLE) or "")
        it = self.db.get_item(iid)
        if not it:
            return
        # 마지막 아이템도 삭제 허용 (빈 상태 허용)
        reply = QMessageBox.question(
            self, "Delete Item",
            f"Delete item '{it.name}' and all its pages?\n(This cannot be undone.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._flush_page_fields_to_model_and_save()
        if not self.db.delete_item(iid):
            return

        # fallback to some existing item (있으면)
        if self.db.items:
            fallback_iid = next(iter(self.db.items.keys()))
            found = self.db.find_item(fallback_iid)
            if found:
                self.current_item_id = fallback_iid
                self.current_category_id = found[1].id
                self.current_page_index = max(0, min(found[0].last_page_index, len(found[0].pages) - 1))
                self._show_placeholder(False)
            else:
                self.current_item_id = ""
                self.current_category_id = self.db.root_category_ids[0] if self.db.root_category_ids else ""
                self._show_placeholder(True)
        else:
            # 아이템이 없으면 빈 상태로
            self.current_item_id = ""
            self.current_category_id = self.db.root_category_ids[0] if self.db.root_category_ids else ""
            self.current_page_index = 0
            self._show_placeholder(True)
        
        self._save_ui_state()
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)
        self._load_current_item_page_to_ui(clear_only=(not self.current_item_id))

    def move_item(self, direction: int) -> None:
        itw = self.nav_tree.currentItem()
        if not itw or itw.data(0, self.NODE_TYPE_ROLE) != "item":
            return
        iid = str(itw.data(0, self.ITEM_ID_ROLE) or "")
        if not iid:
            return
        self.db.move_item_sibling(iid, direction)
        self._save_db_with_warning()
        self._refresh_nav_tree(select_current=True)

    def move_item_to_folder(self) -> None:
        """아이템을 다른 폴더로 이동"""
        itw = self.nav_tree.currentItem()
        if not itw or itw.data(0, self.NODE_TYPE_ROLE) != "item":
            return
        iid = str(itw.data(0, self.ITEM_ID_ROLE) or "")
        it = self.db.get_item(iid)
        if not it:
            return
        
        # 모든 폴더 목록 생성
        folder_list = []
        folder_ids = []
        
        def collect_folders(cid: str, prefix: str = ""):
            cat = self.db.get_category(cid)
            if not cat:
                return
            folder_list.append(f"{prefix}{cat.name}")
            folder_ids.append(cid)
            for child_id in cat.child_ids:
                collect_folders(child_id, prefix + "  ")
        
        for root_id in self.db.root_category_ids:
            collect_folders(root_id)
        
        if not folder_list:
            QMessageBox.warning(self, "No Folders", "이동할 폴더가 없습니다.")
            return
        
        # 현재 폴더는 제외
        current_cat_id = it.category_id
        try:
            current_idx = folder_ids.index(current_cat_id)
            folder_list.pop(current_idx)
            folder_ids.pop(current_idx)
        except ValueError:
            pass
        
        if not folder_list:
            QMessageBox.information(self, "No Other Folders", "다른 폴더가 없습니다.")
            return
        
        # 폴더 선택 다이얼로그
        selected_folder, ok = QInputDialog.getItem(
            self, "Move Item to Folder", 
            f"Move '{it.name}' to:", 
            folder_list, 0, False
        )
        
        if not ok or not selected_folder:
            return
        
        target_idx = folder_list.index(selected_folder)
        target_cat_id = folder_ids[target_idx]
        
        if target_cat_id == current_cat_id:
            return
        
        self._flush_page_fields_to_model_and_save()
        if self.db.move_item_to_category(iid, target_cat_id):
            self.current_category_id = target_cat_id
            self._save_ui_state()
            self._save_db_with_warning()
            self._refresh_nav_tree(select_current=True)
            self.trace(f"Moved item '{it.name}' to folder '{selected_folder}'", "INFO")
        else:
            QMessageBox.warning(self, "Failed", "아이템 이동에 실패했습니다.")

    # ---------------- Rich text ops ----------------
    def _set_active_rich_edit(self, editor: QTextEdit) -> None:
        self._active_rich_edit = editor
        self._sync_format_buttons()

    def _on_any_rich_cursor_changed(self) -> None:
        snd = self.sender()
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
        fmt = QTextListFormat(); fmt.setStyle(style)
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
        self.btn_fmt_bold.blockSignals(True); self.btn_fmt_italic.blockSignals(True); self.btn_fmt_underline.blockSignals(True)
        self.btn_fmt_bold.setChecked(is_bold); self.btn_fmt_italic.setChecked(is_italic); self.btn_fmt_underline.setChecked(is_under)
        self.btn_fmt_bold.blockSignals(False); self.btn_fmt_italic.blockSignals(False); self.btn_fmt_underline.blockSignals(False)

        col = cf.foreground().color() if cf.foreground().style() != Qt.NoBrush else QColor(COLOR_DEFAULT)
        if not col.isValid():
            col = QColor(COLOR_DEFAULT)
        col_hex = col.name().upper()

        def _set_checked(btn: QToolButton, on: bool) -> None:
            btn.blockSignals(True); btn.setChecked(on); btn.blockSignals(False)

        if col_hex == QColor(COLOR_RED).name().upper():
            _set_checked(self.btn_col_red, True)
        elif col_hex == QColor(COLOR_BLUE).name().upper():
            _set_checked(self.btn_col_blue, True)
        elif col_hex == QColor(COLOR_YELLOW).name().upper():
            _set_checked(self.btn_col_yellow, True)
        else:
            _set_checked(self.btn_col_default, True)

    # ---------------- Ideas panel toggle ----------------
    def _on_toggle_ideas(self, checked: bool) -> None:
        self._set_global_ideas_visible(checked, persist=True)

    def _set_global_ideas_visible(self, visible: bool, persist: bool = True) -> None:
        if (not visible) and self.notes_left.isVisible() and self.ideas_panel.isVisible():
            self._remember_notes_splitter_sizes()
        self.ideas_panel.setVisible(bool(visible))
        self.btn_ideas.blockSignals(True); self.btn_ideas.setChecked(bool(visible)); self.btn_ideas.blockSignals(False)
        self._update_text_area_layout()
        if persist:
            self.db.ui_state["global_ideas_visible"] = bool(visible)
            self._save_db_with_warning()

    # ---------------- Description toggle ----------------
    def _on_toggle_desc_clicked(self) -> None:
        """Splitter 핸들 버튼 클릭 시 호출"""
        self._set_desc_visible(not self._desc_visible, persist=True)
    
    def _on_toggle_desc(self, checked: bool) -> None:
        """기존 토글 메서드 (호환성 유지)"""
        self._set_desc_visible(bool(checked), persist=True)

    def _set_desc_visible(self, visible: bool, persist: bool = True) -> None:
        if (not visible) and self.notes_left.isVisible() and self.ideas_panel.isVisible():
            self._remember_notes_splitter_sizes()
        self._desc_visible = bool(visible)
        self.notes_left.setVisible(self._desc_visible)
        
        # 상단 서식 툴바도 함께 숨김/표시
        if hasattr(self, 'fmt_row'):
            self.fmt_row.setVisible(self._desc_visible)
        
        # text_container는 항상 보이게 유지 (splitter 핸들이 보이도록)
        # 대신 splitter 크기를 조정하여 내용만 숨김/표시
        self._adjusting_splitter = True  # splitter 크기 조정 중 플래그 설정
        try:
            if visible:
                # Description이 보일 때: 최소 크기 복원 및 stretch factor 복원
                self.text_container.setMinimumWidth(440)  # Description 최소 크기 복원
                self.page_splitter.setStretchFactor(0, 1)  # Chart
                self.page_splitter.setStretchFactor(1, 1)  # Description
                
                # 이전 크기 복원 또는 기본 크기 설정
                if hasattr(self, '_page_split_prev_sizes') and self._page_split_prev_sizes:
                    def _restore_sizes():
                        self.page_splitter.setSizes(self._page_split_prev_sizes)
                    QTimer.singleShot(10, _restore_sizes)
                else:
                    # 기본 크기 설정 (Chart: 60%, Description: 40%)
                    def _set_default_sizes():
                        total_width = self.page_splitter.width()
                        if total_width <= 0:
                            total_width = self.page_splitter.size().width()
                        if total_width > 0:
                            chart_width = int(total_width * 0.6)
                            desc_width = total_width - chart_width
                            self.page_splitter.setSizes([chart_width, desc_width])
                    QTimer.singleShot(10, _set_default_sizes)
            else:
                # Description이 숨겨질 때: 현재 크기 저장 후 Chart 영역이 전체를 차지하도록
                current_sizes = self.page_splitter.sizes()
                if len(current_sizes) == 2 and current_sizes[1] > 20:
                    self._page_split_prev_sizes = list(current_sizes)
                
                # Chart 영역이 전체를 차지하도록 stretch factor 조정
                self.page_splitter.setStretchFactor(0, 1)  # Chart가 확장 가능하도록
                self.page_splitter.setStretchFactor(1, 0)  # Description은 확장하지 않도록
                
                # Description 영역의 최소 크기를 0으로 설정하여 완전히 접을 수 있도록
                self.text_container.setMinimumWidth(0)
                
                # Chart 영역이 전체를 차지하도록 설정
                def _expand_chart_area():
                    total_width = self.page_splitter.width()
                    if total_width <= 0:
                        total_width = self.page_splitter.size().width()
                    if total_width > 0:
                        # Description 영역을 최소한으로 (splitter 핸들만 보이도록)
                        # 핸들 너비는 보통 5-10px이지만, 더 작게 설정
                        handle_width = 5
                        chart_width = total_width - handle_width
                        # Chart가 전체를 차지하도록 설정
                        self.page_splitter.setSizes([chart_width, handle_width])
                        # 크기가 제대로 설정되었는지 확인하고 재시도
                        actual_sizes = self.page_splitter.sizes()
                        if len(actual_sizes) == 2:
                            # Description 영역이 여전히 크면 다시 시도
                            if actual_sizes[1] > handle_width * 3:
                                chart_width = total_width - handle_width
                                self.page_splitter.setSizes([chart_width, handle_width])
                
                # 즉시 시도하고, 실패하면 지연 후 재시도
                _expand_chart_area()
                QTimer.singleShot(50, _expand_chart_area)
                QTimer.singleShot(100, _expand_chart_area)
                QTimer.singleShot(200, _expand_chart_area)
                QTimer.singleShot(300, _expand_chart_area)
        finally:
            # 플래그 해제 (지연 처리 후)
            QTimer.singleShot(300, lambda: setattr(self, '_adjusting_splitter', False))
        
        # 상단 토글 버튼 상태 업데이트
        self._update_desc_toggle_button_text()
        # Splitter 핸들의 버튼 상태 업데이트 (위젯 추가 후 핸들이 생성되므로 지연 처리)
        QTimer.singleShot(0, lambda: self._update_splitter_handle_state())
        self._update_text_area_layout()
        if persist:
            self.db.ui_state["desc_visible"] = bool(self._desc_visible)
            self._save_db_with_warning()
    
    def _update_desc_toggle_button_text(self) -> None:
        """상단 Description 토글 버튼 텍스트 업데이트"""
        if hasattr(self, 'btn_toggle_desc'):
            self.btn_toggle_desc.blockSignals(True)
            self.btn_toggle_desc.setChecked(self._desc_visible)
            if self._desc_visible:
                self.btn_toggle_desc.setText("Description ✓")
            else:
                self.btn_toggle_desc.setText("Description")
            self.btn_toggle_desc.blockSignals(False)
    
    def _update_splitter_handle_state(self) -> None:
        """Splitter 핸들 상태 업데이트 (지연 호출)"""
        if hasattr(self.page_splitter, 'set_description_visible'):
            self.page_splitter.set_description_visible(self._desc_visible)

    def _collapse_text_container(self, collapse: bool) -> None:
        """text_container 축소/확장 - 이제는 splitter 크기만 조정 (항상 보이게 유지)"""
        if collapse:
            # 최소 크기로 축소 (splitter 핸들이 보이도록 10px 유지)
            total = max(1, self.page_splitter.width())
            self.page_splitter.setSizes([max(1, total - 10), 10])
        else:
            # 이전 크기 복원 또는 기본 크기 설정
            ps = self.db.ui_state.get("page_splitter_sizes")
            if self._is_valid_splitter_sizes(ps):
                self.page_splitter.setSizes(ps)
            elif self._page_split_prev_sizes and len(self._page_split_prev_sizes) == 2:
                self.page_splitter.setSizes(self._page_split_prev_sizes)
            else:
                total = max(1, self.page_splitter.width())
                chart_width = int(total * 0.6)
                desc_width = total - chart_width
                self.page_splitter.setSizes([chart_width, desc_width])

    def _apply_notes_splitter_sizes_both_visible(self, total: int) -> None:
        ns = self.db.ui_state.get("notes_splitter_sizes")
        if self._is_valid_notes_sizes_for_both_visible(ns):
            self.notes_ideas_splitter.setSizes([int(ns[0]), int(ns[1])])
            return
        if self._notes_split_prev_sizes and self._is_valid_notes_sizes_for_both_visible(self._notes_split_prev_sizes):
            self.notes_ideas_splitter.setSizes([int(self._notes_split_prev_sizes[0]), int(self._notes_split_prev_sizes[1])])
            return
        right = max(320, min(520, int(total * 0.34)))
        left = max(220, total - right)
        self.notes_ideas_splitter.setSizes([left, right])

    def _update_text_area_layout(self) -> None:
        ideas_vis = bool(self.ideas_panel.isVisible())
        desc_vis = bool(self._desc_visible)
        if not desc_vis and not ideas_vis:
            self._collapse_text_container(True)
            return
        self._collapse_text_container(False)
        total = max(1, self.notes_ideas_splitter.width())
        if desc_vis and ideas_vis:
            self._apply_notes_splitter_sizes_both_visible(total)
        elif desc_vis and (not ideas_vis):
            self.notes_ideas_splitter.setSizes([total, 0])
        elif (not desc_vis) and ideas_vis:
            self.notes_ideas_splitter.setSizes([0, total])

    # ---------------- Event filter (active pane + resize overlay) ----------------
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
