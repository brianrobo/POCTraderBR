"""
원하시면 다음 단계로는 더 “OneNote 느낌” 나게:

Annotate를 **이미지 위에 겹치는 오버레이 패널(작게 떠 있는 패널)**로 바꾸고,

평소엔 아이콘 1개만 보이다가 누르면 패널이 열리는 형태
로도 바로 개선 가능합니다.
------------------------------

응 그렇게 개선해줘


그리고, step 별로 category tag 같은걸 달아서,,  같은 category tag인 step끼리는 같이 묶여있었으면해, ui상으로는 tree형식이 되어야겠고
28s 동안 생각함
------------------------------

좋습니다. 요청하신 2가지를 모두 반영해서 v0.3.0 전체 코드로 업데이트했습니다.

반영 사항 (v0.3.0)

Annotate를 “오버레이 패널(이미지 위에 떠 있는 패널)”로 변경

평소엔 이미지 우측 상단에 **작은 버튼(✎)**만 보임

누르면 Annotate 패널이 이미지 위에 오버레이로 펼쳐짐

닫으면 다시 ✎ 버튼만 보임

패널을 닫을 때 Draw가 켜져 있으면 자동 OFF + Pan 모드로 전환

Step에 Category Tag 추가 + 좌측 UI를 Tree 형태로 그룹핑

Step마다 category 필드 저장 (JSON 유지)

좌측이 Category → Step 트리 구조로 표시됨

+Step 시 Step 이름 입력 후, Category 입력(기존 카테고리 참고 가능)

Set Category 버튼으로 선택 Step의 카테고리를 변경 가능

"""


# -*- coding: utf-8 -*-
"""
Trader Chart Note App (PyQt5) - OneNote-style Step/Page Navigator

Version: 0.3.0  (2025-12-20)
Versioning: MAJOR.MINOR.PATCH (SemVer)

Release Notes (v0.3.0):
- Annotate UI를 오버레이 패널로 변경:
  - 이미지 우측 상단에 ✎ 버튼만 보이다가 클릭 시 패널 표시
  - 패널 닫으면 다시 ✎ 버튼만 표시
  - 패널 닫을 때 Draw가 켜져 있으면 자동 OFF + Pan 전환
- Step에 Category Tag 추가 + 좌측 Step UI를 Tree로 구성:
  - Category(상위) → Step(하위) 구조
  - Step별 category 저장/로드(JSON)
  - Set Category 버튼으로 카테고리 변경 가능
- 기존 기능 유지:
  - JSON 저장
  - 이미지 Zoom/Pan + Draw(Shift 직선) + 색/두께 + Clear Lines(confirm)
  - Checklist(4문항) + Description
  - 페이지 네비게이션(◀ 1/3 ▶ +Page Del Page) 좌측 이미지 섹션 하단 위치
  - Del Page confirm 팝업
  - Clipboard 이미지 붙여넣기 저장 (Ctrl+V: image_viewer에 포커스일 때)

Run:
  python trader_note_app.py

Dependencies:
  pip install PyQt5
"""

import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF, QRect, QSize, QPoint, QEvent
from PyQt5.QtGui import (
    QImage,
    QKeySequence,
    QPixmap,
    QPainterPath,
    QPen,
    QColor,
    QPainter,
    QIcon,
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
    QSizePolicy,
    QFrame,
    QTreeWidget,
    QTreeWidgetItem,
)


APP_TITLE = "Trader Chart Note (v0.3.0)"
DEFAULT_DB_PATH = os.path.join("data", "notes_db.json")
ASSETS_DIR = "assets"


DEFAULT_CHECK_QUESTIONS = [
    "Q. 매집구간이 보이는가?",
    "Q. 매물이 모두 정리가 되었는가? 그럴만한 상승구간과 거래량이 나왔는가?",
    "Q. 그렇지 않다면 지지선, 깨지말아야할 선은 무엇인가?",
    "Q. 돌아서는 구간을 찾을 수 있는가?",
]


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
                color = str(s.get("color", "#FF3C3C"))
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
            out2.append({"color": "#FF3C3C", "width": 3.0, "points": stroke})
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
    image_path: str
    note_text: str
    stock_name: str
    ticker: str
    strokes: Strokes
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
        self.steps = self._parse_steps(self.data.get("steps", []))

        if not self.steps:
            self.steps = self._parse_steps(self._default_data()["steps"])

        for st in self.steps:
            if not st.pages:
                st.pages.append(self.new_page())

    def save(self) -> None:
        self.data["version"] = "0.3.0"
        self.data["updated_at"] = _now_epoch()
        self.data["steps"] = self._serialize_steps(self.steps)
        self.data["ui_state"] = self.ui_state
        _safe_write_json(self.db_path, self.data)

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
                            "image_path": "",
                            "note_text": "",
                            "stock_name": "",
                            "ticker": "",
                            "strokes": [],
                            "checklist": _default_checklist(),
                            "created_at": _now_epoch(),
                            "updated_at": _now_epoch(),
                        }
                    ],
                }
            )
        return {
            "version": "0.3.0",
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
                raw_strokes = p.get("strokes", None)
                if raw_strokes is None:
                    raw_strokes = p.get("annotations", [])
                strokes = _normalize_strokes(raw_strokes)
                checklist = _normalize_checklist(p.get("checklist", None))

                pages.append(
                    Page(
                        id=str(p.get("id", _uuid())),
                        image_path=str(p.get("image_path", "")),
                        note_text=str(p.get("note_text", "")),
                        stock_name=str(p.get("stock_name", "")),
                        ticker=str(p.get("ticker", "")),
                        strokes=strokes,
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
                            "image_path": pg.image_path,
                            "note_text": pg.note_text,
                            "stock_name": pg.stock_name,
                            "ticker": pg.ticker,
                            "strokes": pg.strokes,
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
            image_path="",
            note_text="",
            stock_name="",
            ticker="",
            strokes=[],
            checklist=_default_checklist(),
            created_at=now,
            updated_at=now,
        )

    def get_step_by_id(self, step_id: str) -> Optional[Step]:
        for st in self.steps:
            if st.id == step_id:
                return st
        return None

    def add_step(self, name: str, category: str) -> Step:
        category = (category or "").strip() or "General"
        st = Step(id=_uuid(), name=name, category=category, pages=[self.new_page()], last_page_index=0)
        self.steps.append(st)
        return st

    def delete_step(self, step_id: str) -> bool:
        if len(self.steps) <= 1:
            return False
        self.steps = [s for s in self.steps if s.id != step_id]
        return True

    def list_categories(self) -> List[str]:
        cats = sorted({(s.category or "General").strip() or "General" for s in self.steps})
        return cats


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

        self._pen_color = QColor("#FF3C3C")
        self._pen_width = 3.0

        self._current_path: Optional[QPainterPath] = None
        self._current_item: Optional[QGraphicsPathItem] = None
        self._current_points: List[List[float]] = []
        self._stroke_start: Optional[QPointF] = None
        self._stroke_color_hex: str = "#FF3C3C"
        self._stroke_width: float = 3.0

        self._strokes: Strokes = []
        self._stroke_items: List[QGraphicsPathItem] = []

        self.set_mode_pan()

    def set_pen(self, color_hex: str, width: float) -> None:
        c = QColor(color_hex)
        if not c.isValid():
            c = QColor("#FF3C3C")
        self._pen_color = c
        self._pen_width = float(width)

    def _make_pen(self, color_hex: str, width: float) -> QPen:
        c = QColor(color_hex)
        if not c.isValid():
            c = QColor("#FF3C3C")
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
        self._scene.clear()
        self._pixmap_item = None
        self._has_image = False
        self.resetTransform()
        self._clear_strokes_internal(emit_signal=False)

    def set_image_path(self, abs_path: str) -> None:
        pm = QPixmap(abs_path)
        if pm.isNull():
            self.clear_image()
            return
        self._set_pixmap(pm)

    def _set_pixmap(self, pm: QPixmap) -> None:
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pm)
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._pixmap_item.setZValue(0)

        self._has_image = True
        self._scene.setSceneRect(QRectF(pm.rect()))
        self.resetTransform()
        self.fit_to_view()
        self._clear_strokes_internal(emit_signal=False)

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
            color = str(s.get("color", "#FF3C3C"))
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
        for it in self._stroke_items:
            self._scene.removeItem(it)
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
                self._scene.removeItem(self._current_item)
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
        self.resize(1400, 930)

        self.db = NoteDB(DEFAULT_DB_PATH)

        self.current_step_id: Optional[str] = None
        self.current_page_index: int = 0
        self._loading_ui: bool = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_page_fields_to_model_and_save)

        self._build_ui()
        self._build_annotate_overlay()

        self._load_ui_state_or_defaults()
        self._refresh_steps_tree(select_current=True)
        self._load_current_page_to_ui()

        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_prev_page)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.go_next_page)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_page)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.force_save)
        QShortcut(QKeySequence("Ctrl+V"), self.image_viewer, activated=self.paste_image_from_clipboard)

    def closeEvent(self, event) -> None:
        try:
            self._flush_page_fields_to_model_and_save()
            self.db.save()
        except Exception:
            pass
        super().closeEvent(event)

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
        self.btn_rename_step.setText("Rename")
        self.btn_set_category = QToolButton()
        self.btn_set_category.setText("Set Category")
        self.btn_del_step = QToolButton()
        self.btn_del_step.setText("Del")

        self.btn_add_step.clicked.connect(self.add_step)
        self.btn_rename_step.clicked.connect(self.rename_step)
        self.btn_set_category.clicked.connect(self.set_step_category)
        self.btn_del_step.clicked.connect(self.delete_step)

        step_controls_layout.addWidget(self.btn_add_step)
        step_controls_layout.addWidget(self.btn_rename_step)
        step_controls_layout.addWidget(self.btn_set_category)
        step_controls_layout.addWidget(self.btn_del_step)

        self.steps_tree = QTreeWidget()
        self.steps_tree.setHeaderHidden(True)
        self.steps_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.steps_tree.setUniformRowHeights(True)

        left_layout.addWidget(step_controls)
        left_layout.addWidget(self.steps_tree, 1)

        # Right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.page_splitter = QSplitter(Qt.Horizontal)

        # ---------------- Image section ----------------
        img_container = QWidget()
        img_layout = QVBoxLayout(img_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(6)

        # Meta (wrap)
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

        # Toolbar (wrap) - annotate는 오버레이이므로 여기서 제거
        toolbar_widget = QWidget()
        toolbar_flow = FlowLayout(toolbar_widget, margin=0, spacing=6)

        self.btn_set_image = QPushButton("Open")
        self.btn_set_image.setToolTip("Open image file and set as chart image")
        self.btn_paste_image = QPushButton("Paste")
        self.btn_paste_image.setToolTip("Paste chart image from clipboard (Ctrl+V)")
        self.btn_clear_image = QPushButton("Clr Img")
        self.btn_clear_image.setToolTip("Clear chart image for this page")
        self.btn_reset_view = QPushButton("Fit")
        self.btn_reset_view.setToolTip("Fit image to view (reset zoom/pan)")

        self.btn_set_image.clicked.connect(self.set_image_via_dialog)
        self.btn_paste_image.clicked.connect(self.paste_image_from_clipboard)
        self.btn_clear_image.clicked.connect(self.clear_image)
        self.btn_reset_view.clicked.connect(self.reset_image_view)

        toolbar_flow.addWidget(self.btn_set_image)
        toolbar_flow.addWidget(self.btn_paste_image)
        toolbar_flow.addWidget(self.btn_clear_image)
        toolbar_flow.addWidget(self.btn_reset_view)

        self.image_viewer = ZoomPanAnnotateView()
        self.image_viewer.imageDropped.connect(self._on_image_dropped)
        self.image_viewer.strokesChanged.connect(self._on_page_field_changed)
        self.image_viewer.viewport().installEventFilter(self)  # overlay reposition용

        # Navigator (still inside image section bottom)
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

        img_layout.addWidget(meta_widget)
        img_layout.addWidget(toolbar_widget)
        img_layout.addWidget(self.image_viewer, 1)
        img_layout.addWidget(nav_widget)

        # ---------------- Text section ----------------
        text_container = QWidget()
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

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
            note.setPlaceholderText("간단 설명을 입력하세요...")
            note.setFixedHeight(54)
            note.textChanged.connect(self._on_page_field_changed)
            self.chk_notes.append(note)

            chk_layout.addWidget(cb)
            chk_layout.addWidget(note)

        text_header = QWidget()
        text_header_flow = FlowLayout(text_header, margin=0, spacing=6)

        self.text_title = QLabel("Description")
        self.btn_clear_text = QPushButton("Clear Text")
        self.btn_clear_text.clicked.connect(self.clear_text)

        text_header_flow.addWidget(self.text_title)
        text_header_flow.addWidget(self.btn_clear_text)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("추가 분석/설명을 자유롭게 작성하세요...")
        self.text_edit.textChanged.connect(self._on_page_field_changed)

        text_layout.addWidget(self.chk_group)
        text_layout.addWidget(text_header)
        text_layout.addWidget(self.text_edit, 1)

        self.page_splitter.addWidget(img_container)
        self.page_splitter.addWidget(text_container)
        self.page_splitter.setStretchFactor(0, 1)
        self.page_splitter.setStretchFactor(1, 1)

        right_layout.addWidget(self.page_splitter, 1)

        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([320, 1080])

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

    # ---------------- Annotate Overlay ----------------
    def _build_annotate_overlay(self) -> None:
        vp = self.image_viewer.viewport()

        # Closed state: small toggle button
        self.btn_anno_toggle = QToolButton(vp)
        self.btn_anno_toggle.setText("✎")
        self.btn_anno_toggle.setToolTip("Open Annotate panel")
        self.btn_anno_toggle.setAutoRaise(True)
        self.btn_anno_toggle.setFixedSize(34, 30)
        self.btn_anno_toggle.clicked.connect(self._open_annotate_panel)

        # Panel (floating)
        self.anno_panel = QFrame(vp)
        self.anno_panel.setObjectName("anno_panel")
        self.anno_panel.setFrameShape(QFrame.StyledPanel)
        self.anno_panel.setVisible(False)
        self.anno_panel.setFixedWidth(240)

        self.anno_panel.setStyleSheet("""
            QFrame#anno_panel {
                background: rgba(255, 255, 255, 235);
                border: 1px solid #9A9A9A;
                border-radius: 10px;
            }
            QLabel { color: #222; }
        """)

        p_layout = QVBoxLayout(self.anno_panel)
        p_layout.setContentsMargins(10, 10, 10, 10)
        p_layout.setSpacing(8)

        # Header row
        header = QWidget(self.anno_panel)
        header_l = QHBoxLayout(header)
        header_l.setContentsMargins(0, 0, 0, 0)
        header_l.setSpacing(6)

        lbl = QLabel("Annotate", header)
        lbl.setStyleSheet("font-weight: 600;")
        header_l.addWidget(lbl, 1)

        self.btn_anno_close = QToolButton(header)
        self.btn_anno_close.setText("×")
        self.btn_anno_close.setToolTip("Close panel")
        self.btn_anno_close.setAutoRaise(True)
        self.btn_anno_close.setFixedSize(26, 22)
        self.btn_anno_close.clicked.connect(self._close_annotate_panel)
        header_l.addWidget(self.btn_anno_close)

        p_layout.addWidget(header)

        # Draw toggle
        self.btn_draw_mode = QToolButton(self.anno_panel)
        self.btn_draw_mode.setText("Draw")
        self.btn_draw_mode.setCheckable(True)
        self.btn_draw_mode.setToolTip("Toggle draw mode. Drag to draw. Hold SHIFT for straight line.")
        self.btn_draw_mode.toggled.connect(self.toggle_draw_mode)
        p_layout.addWidget(self.btn_draw_mode)

        # Color row
        color_row = QWidget(self.anno_panel)
        color_l = QHBoxLayout(color_row)
        color_l.setContentsMargins(0, 0, 0, 0)
        color_l.setSpacing(6)
        color_l.addWidget(QLabel("Color"))
        self.combo_color = QComboBox(color_row)
        self.combo_color.addItem("Red", "#FF3C3C")
        self.combo_color.addItem("Yellow", "#FFD400")
        self.combo_color.addItem("Cyan", "#00D5FF")
        self.combo_color.addItem("White", "#FFFFFF")
        self.combo_color.currentIndexChanged.connect(self._on_pen_changed)
        color_l.addWidget(self.combo_color, 1)
        p_layout.addWidget(color_row)

        # Width row
        width_row = QWidget(self.anno_panel)
        width_l = QHBoxLayout(width_row)
        width_l.setContentsMargins(0, 0, 0, 0)
        width_l.setSpacing(6)
        width_l.addWidget(QLabel("Width"))
        self.combo_width = QComboBox(width_row)
        for w in ["2", "3", "4", "6", "8"]:
            self.combo_width.addItem(f"{w}px", float(w))
        self.combo_width.setCurrentIndex(1)
        self.combo_width.currentIndexChanged.connect(self._on_pen_changed)
        width_l.addWidget(self.combo_width, 1)
        p_layout.addWidget(width_row)

        # Clear lines
        self.btn_clear_lines = QPushButton("Clear Lines", self.anno_panel)
        self.btn_clear_lines.clicked.connect(self.clear_lines)
        p_layout.addWidget(self.btn_clear_lines)

        help_lbl = QLabel(
            "• Wheel: Zoom\n"
            "• Drag: Pan (Draw OFF)\n"
            "• Drag: Draw (Draw ON)\n"
            "• Shift+Drag: Straight line\n"
            "• Ctrl+V: Paste image\n"
            "• Alt+←/→: Prev/Next\n"
            "• Ctrl+N: Add page, Ctrl+S: Save",
            self.anno_panel
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color:#555; font-size: 11px;")
        p_layout.addWidget(help_lbl)

        self._apply_pen_from_ui()
        self._reposition_overlay()

    def _open_annotate_panel(self) -> None:
        self.btn_anno_toggle.setVisible(False)
        self.anno_panel.setVisible(True)
        self._reposition_overlay()

    def _close_annotate_panel(self) -> None:
        # 패널 닫을 때 draw가 켜져 있으면 안전하게 OFF
        if self.btn_draw_mode.isChecked():
            self.btn_draw_mode.setChecked(False)
            self.image_viewer.set_mode_pan()

        self.anno_panel.setVisible(False)
        self.btn_anno_toggle.setVisible(True)
        self._reposition_overlay()

    def _reposition_overlay(self) -> None:
        vp = self.image_viewer.viewport()
        w = vp.width()
        margin = 10

        # toggle button 위치 (항상 우상단)
        self.btn_anno_toggle.move(max(margin, w - self.btn_anno_toggle.width() - margin), margin)

        if self.anno_panel.isVisible():
            # panel도 우상단(토글버튼 자리 근처)로 배치
            x = max(margin, w - self.anno_panel.width() - margin)
            y = margin
            self.anno_panel.move(x, y)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.image_viewer.viewport() and event.type() == QEvent.Resize:
            self._reposition_overlay()
        return super().eventFilter(obj, event)

    # ---------------- Pen UI ----------------
    def _apply_pen_from_ui(self) -> None:
        color_hex = str(self.combo_color.currentData())
        width = float(self.combo_width.currentData())
        self.image_viewer.set_pen(color_hex, width)

    def _on_pen_changed(self) -> None:
        self._apply_pen_from_ui()

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

    # ---------------- Tree: category -> steps ----------------
    def _refresh_steps_tree(self, select_current: bool = False) -> None:
        self.steps_tree.blockSignals(True)
        self.steps_tree.clear()

        # category -> items
        cats = self.db.list_categories()
        cat_nodes: Dict[str, QTreeWidgetItem] = {}

        # Create category nodes
        for cat in cats:
            top = QTreeWidgetItem([cat])
            top.setData(0, self.NODE_TYPE_ROLE, "category")
            top.setData(0, self.CATEGORY_NAME_ROLE, cat)
            top.setFlags(top.flags() & ~Qt.ItemIsSelectable)  # category는 선택 불가(오작동 방지)
            self.steps_tree.addTopLevelItem(top)
            cat_nodes[cat] = top

        # Put steps under category
        selected_item: Optional[QTreeWidgetItem] = None
        for st in self.db.steps:
            cat = (st.category or "General").strip() or "General"
            if cat not in cat_nodes:
                top = QTreeWidgetItem([cat])
                top.setData(0, self.NODE_TYPE_ROLE, "category")
                top.setData(0, self.CATEGORY_NAME_ROLE, cat)
                top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
                self.steps_tree.addTopLevelItem(top)
                cat_nodes[cat] = top

            child = QTreeWidgetItem([st.name])
            child.setData(0, self.NODE_TYPE_ROLE, "step")
            child.setData(0, self.STEP_ID_ROLE, st.id)
            cat_nodes[cat].addChild(child)

            if select_current and st.id == self.current_step_id:
                selected_item = child

        # Expand all categories (원하면 ui_state로 확장상태 저장 가능)
        for i in range(self.steps_tree.topLevelItemCount()):
            self.steps_tree.topLevelItem(i).setExpanded(True)

        # Select current
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

    # ---------------- Page load/save ----------------
    def _load_current_page_to_ui(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            self._loading_ui = True
            try:
                self.edit_stock_name.clear()
                self.edit_ticker.clear()
                for cb in self.chk_boxes:
                    cb.setChecked(False)
                for note in self.chk_notes:
                    note.clear()
                self.text_edit.clear()
                self.image_viewer.clear_image()
                self.btn_draw_mode.setChecked(False)
                self._update_nav()
            finally:
                self._loading_ui = False
            return

        self._loading_ui = True
        try:
            self.edit_stock_name.setText(pg.stock_name or "")
            self.edit_ticker.setText(pg.ticker or "")

            if pg.image_path:
                abs_path = _abspath_from_rel(pg.image_path)
                if os.path.exists(abs_path):
                    self.image_viewer.set_image_path(abs_path)
                else:
                    self.image_viewer.clear_image()
            else:
                self.image_viewer.clear_image()

            self.image_viewer.set_strokes(pg.strokes or [])

            cl = _normalize_checklist(pg.checklist)
            for i in range(len(DEFAULT_CHECK_QUESTIONS)):
                self.chk_boxes[i].setChecked(bool(cl[i].get("checked", False)))
                self.chk_notes[i].setPlainText(str(cl[i].get("note", "")))

            self.text_edit.setPlainText(pg.note_text or "")

            # 페이지 로드시 draw는 안전하게 off
            self.btn_draw_mode.setChecked(False)
            self.image_viewer.set_mode_pan()

            self._update_nav()
        finally:
            self._loading_ui = False

    def _on_page_field_changed(self) -> None:
        if self._loading_ui:
            return
        self._save_timer.start(450)

    def _collect_checklist_from_ui(self) -> Checklist:
        out: Checklist = []
        for i, q in enumerate(DEFAULT_CHECK_QUESTIONS):
            out.append({"q": q, "checked": bool(self.chk_boxes[i].isChecked()), "note": self.chk_notes[i].toPlainText()})
        return out

    def _flush_page_fields_to_model_and_save(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg or self._loading_ui:
            return

        changed = False

        new_text = self.text_edit.toPlainText()
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

        new_strokes = self.image_viewer.get_strokes()
        if pg.strokes != new_strokes:
            pg.strokes = new_strokes
            changed = True

        new_checklist = self._collect_checklist_from_ui()
        if pg.checklist != new_checklist:
            pg.checklist = new_checklist
            changed = True

        st.last_page_index = self.current_page_index
        self._save_ui_state()

        if changed:
            pg.updated_at = _now_epoch()
        self.db.save()

    def force_save(self) -> None:
        self._flush_page_fields_to_model_and_save()
        QMessageBox.information(self, "Saved", "Saved to JSON.")

    def _update_nav(self) -> None:
        st = self.current_step()
        total = len(st.pages) if st else 0
        cur = (self.current_page_index + 1) if total > 0 else 0
        self.lbl_page.setText(f"{cur} / {total}")

        self.btn_prev.setEnabled(total > 0 and self.current_page_index > 0)
        self.btn_next.setEnabled(total > 0 and self.current_page_index < total - 1)
        self.btn_del_page.setEnabled(total > 1)

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
        self.db.save()
        self._load_current_page_to_ui()

    def delete_page(self) -> None:
        st = self.current_step()
        if not st or len(st.pages) <= 1:
            return

        reply = QMessageBox.question(
            self,
            "Delete Page",
            "Delete current page?\n(This cannot be undone in v0.3.x.)",
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
        self.db.save()
        self._load_current_page_to_ui()

    # ---------------- Image handling ----------------
    def reset_image_view(self) -> None:
        self.image_viewer.fit_to_view()
        self.image_viewer.setFocus(Qt.MouseFocusReason)

    def toggle_draw_mode(self, checked: bool) -> None:
        if checked:
            self.image_viewer.set_mode_draw()
        else:
            self.image_viewer.set_mode_pan()
        self.image_viewer.setFocus(Qt.MouseFocusReason)

    def clear_lines(self) -> None:
        pg = self.current_page()
        if not pg:
            return
        if not self.image_viewer.get_strokes():
            return

        reply = QMessageBox.question(
            self,
            "Clear Lines",
            "Clear all annotation lines on this page?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.image_viewer.clear_strokes()
        self._flush_page_fields_to_model_and_save()
        self.image_viewer.setFocus(Qt.MouseFocusReason)

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
        self._flush_page_fields_to_model_and_save()
        pg.image_path = ""
        pg.strokes = []
        pg.updated_at = _now_epoch()
        self.db.save()
        self.image_viewer.clear_image()

    def paste_image_from_clipboard(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            return

        cb = QApplication.clipboard()
        img: QImage = cb.image()
        if img.isNull():
            QMessageBox.information(self, "Paste Image", "Clipboard does not contain an image.")
            return

        self._flush_page_fields_to_model_and_save()

        safe_step = _sanitize_for_folder(st.name, st.id[:8])
        dst_dir = os.path.join(ASSETS_DIR, safe_step)
        _ensure_dir(dst_dir)

        dst_name = f"{pg.id}_clip_{_now_epoch()}.png"
        dst_rel = _relpath_norm(os.path.join(dst_dir, dst_name))
        dst_abs = _abspath_from_rel(dst_rel)

        ok = img.save(dst_abs, "PNG")
        if not ok:
            QMessageBox.warning(self, "Paste failed", "Clipboard image could not be saved as PNG.")
            return

        pg.image_path = dst_rel
        pg.strokes = []
        pg.updated_at = _now_epoch()
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self.db.save()

        self.image_viewer.set_image_path(dst_abs)
        self.image_viewer.set_strokes([])
        self.image_viewer.setFocus(Qt.MouseFocusReason)

    def _set_image_from_file(self, src_path: str) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            return
        if not os.path.isfile(src_path):
            return

        self._flush_page_fields_to_model_and_save()

        ext = os.path.splitext(src_path)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]:
            QMessageBox.warning(self, "Invalid file", "Please select an image file.")
            return

        safe_step = _sanitize_for_folder(st.name, st.id[:8])
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
        pg.strokes = []
        pg.updated_at = _now_epoch()
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self.db.save()

        self.image_viewer.set_image_path(dst_abs)
        self.image_viewer.set_strokes([])
        self.image_viewer.setFocus(Qt.MouseFocusReason)

    # ---------------- Text/meta utilities ----------------
    def clear_text(self) -> None:
        self.text_edit.clear()

    def copy_ticker(self) -> None:
        txt = self.edit_ticker.text().strip()
        if not txt:
            QMessageBox.information(self, "Copy Ticker", "Ticker is empty.")
            return
        QApplication.clipboard().setText(txt)

    # ---------------- Step management ----------------
    def _prompt_step_name_and_category(self, default_name: str = "", default_category: str = "") -> Optional[Tuple[str, str]]:
        name, ok = QInputDialog.getText(self, "Step Name", "Step name:", text=default_name)
        if not ok or not name.strip():
            return None

        cats = self.db.list_categories()
        # getItem은 editable=False가 기본이라, 카테고리 신규 입력을 위해 getText를 사용하되
        # 참고로 기존 카테고리 목록을 안내한다.
        hint = ", ".join(cats) if cats else "General"
        cat_text, ok2 = QInputDialog.getText(
            self,
            "Category",
            f"Category tag (existing: {hint}):",
            text=(default_category.strip() or "General"),
        )
        if not ok2:
            return None

        category = (cat_text or "").strip() or "General"
        return name.strip(), category

    def add_step(self) -> None:
        self._flush_page_fields_to_model_and_save()

        res = self._prompt_step_name_and_category(default_name="New Step", default_category="General")
        if not res:
            return
        name, category = res

        st = self.db.add_step(name, category)
        self.current_step_id = st.id
        self.current_page_index = 0
        self._save_ui_state()
        self.db.save()

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
        self.db.save()
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
        self.db.save()
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
            f"Delete step '{st.name}' (Category: {st.category}) and all its pages?\n(This cannot be undone in v0.3.x.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        ok = self.db.delete_step(st.id)
        if not ok:
            QMessageBox.warning(self, "Failed", "Cannot delete the last remaining step.")
            return

        # fallback to first step
        self.current_step_id = self.db.steps[0].id
        first = self.db.steps[0]
        self.current_page_index = max(0, min(first.last_page_index, len(first.pages) - 1))
        self._save_ui_state()
        self.db.save()

        self._refresh_steps_tree(select_current=True)
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
