
"""
이미지에, 그냥 원본을 그대로 두고,, 그냥 선을 그릴 수 있고, clear하면 다시 그린 선 삭제되는게 되었으면 좋겠어. 
이런 기능이 있으면 차트에서 어떤 포인트나 설명을 하기가 더 쉬워서
23s 동안 생각함

-------------------------
가능합니다. 핵심은 원본 이미지는 QGraphicsPixmapItem으로 그대로 두고, 그 위에 **선(주석)을 QGraphicsPathItem으로 “오버레이”**로 얹는 방식입니다. 그러면 원본 파일은 절대 변경되지 않고, Clear 하면 오버레이만 삭제됩니다.

아래는 기존 v0.1.2 코드에 기능을 반영한 v0.1.3 전체 코드입니다.

이미지 영역 툴바에 Draw(토글), Clear Lines 버튼 추가

Draw 모드일 때: 마우스 좌클릭 드래그로 자유선(스트로크) 그리기

Pan 모드일 때: 기존처럼 좌클릭 드래그로 이동

Wheel 줌은 항상 동작

선은 JSON에 페이지별로 저장됩니다(원본 이미지는 그대로, 오버레이 좌표만 저장).
즉, 페이지 이동해도 선이 유지됩니다. Clear Lines는 저장된 선까지 삭제합니다.
-----------------
사용 방법

Pan(이동): Draw 버튼 OFF 상태에서 좌클릭 드래그

Draw(선 그리기): Draw 버튼 ON → 좌클릭 드래그로 자유선

줌: 마우스 휠

Reset View: 화면 맞춤

Clear Lines: 그려진 선만 삭제(원본 이미지 파일은 그대로)



"""



# -*- coding: utf-8 -*-
"""
Trader Chart Note App (PyQt5) - OneNote-style Step/Page Navigator

Version: 0.1.3  (2025-12-20)
Versioning: MAJOR.MINOR.PATCH (SemVer)

Release Notes (v0.1.3):
- Image annotation overlay (non-destructive):
  - Original image stays unchanged
  - Draw lines on top (overlay) in Draw mode
  - Clear Lines removes only drawn strokes (overlay)
  - Annotations are persisted in JSON per page (no image modification)
- Image Zoom/Pan kept:
  - Mouse wheel zoom
  - Pan in Pan mode (hand drag)
  - Reset View to fit
- Per-page instrument metadata:
  - Stock Name + Ticker editable
  - Copy Ticker button

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

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF
from PyQt5.QtGui import QImage, QKeySequence, QPixmap, QPainterPath, QPen, QColor
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)


APP_TITLE = "Trader Chart Note (v0.1.3)"
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


def _sanitize_for_folder(name: str, fallback: str) -> str:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "_", "-")).strip().replace(" ", "_")
    return safe or fallback


# annotations: list of strokes, each stroke is list of [x, y] points in scene coordinates
Annotations = List[List[List[float]]]


@dataclass
class Page:
    id: str
    image_path: str  # relative path under project
    note_text: str
    stock_name: str
    ticker: str
    annotations: Annotations
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
        self.data["version"] = "0.1.3"
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
                    "last_page_index": 0,
                    "pages": [
                        {
                            "id": _uuid(),
                            "image_path": "",
                            "note_text": "",
                            "stock_name": "",
                            "ticker": "",
                            "annotations": [],
                            "created_at": _now_epoch(),
                            "updated_at": _now_epoch(),
                        }
                    ],
                }
            )
        return {
            "version": "0.1.3",
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
                anns = p.get("annotations", [])
                if not isinstance(anns, list):
                    anns = []
                pages.append(
                    Page(
                        id=str(p.get("id", _uuid())),
                        image_path=str(p.get("image_path", "")),
                        note_text=str(p.get("note_text", "")),
                        stock_name=str(p.get("stock_name", "")),
                        ticker=str(p.get("ticker", "")),
                        annotations=anns,  # type: ignore
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
                            "stock_name": pg.stock_name,
                            "ticker": pg.ticker,
                            "annotations": pg.annotations,
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
            annotations=[],
            created_at=now,
            updated_at=now,
        )

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


class ZoomPanAnnotateView(QGraphicsView):
    """
    QGraphicsView 기반 이미지 뷰어
    - Wheel: Zoom
    - Pan mode: 좌클릭 드래그로 이동(ScrollHandDrag)
    - Draw mode: 좌클릭 드래그로 선(자유선) 그리기 (원본 이미지 비파괴)
    - annotations는 scene 좌표로 저장/복원
    """
    imageDropped = pyqtSignal(str)
    annotationsChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._has_image: bool = False

        # Zoom behavior
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._zoom_factor_step = 1.25
        self._min_scale = 0.05
        self._max_scale = 20.0

        # Modes
        self._draw_mode: bool = False
        self._is_drawing: bool = False

        # Current stroke
        self._current_path: Optional[QPainterPath] = None
        self._current_item: Optional[QGraphicsPathItem] = None
        self._current_points: List[List[float]] = []

        # All strokes
        self._strokes: Annotations = []
        self._stroke_items: List[QGraphicsPathItem] = []

        # Pen (overlay only)
        self._pen = QPen(QColor(255, 60, 60), 3.0)  # red, 3px
        self._pen.setCapStyle(Qt.RoundCap)
        self._pen.setJoinStyle(Qt.RoundJoin)

        self.set_mode_pan()

    # ----- Mode control -----
    def is_draw_mode(self) -> bool:
        return self._draw_mode

    def set_mode_draw(self) -> None:
        self._draw_mode = True
        self.setDragMode(QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.CrossCursor)

    def set_mode_pan(self) -> None:
        self._draw_mode = False
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.viewport().setCursor(Qt.OpenHandCursor)

    # ----- Image control -----
    def has_image(self) -> bool:
        return self._has_image

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._has_image = False
        self.resetTransform()
        self._clear_annotations_internal(emit_signal=False)

    def set_image_path(self, abs_path: str) -> None:
        pm = QPixmap(abs_path)
        if pm.isNull():
            self.clear_image()
            return
        self._set_pixmap(pm)

    def set_qimage(self, img: QImage) -> bool:
        if img.isNull():
            return False
        pm = QPixmap.fromImage(img)
        if pm.isNull():
            return False
        self._set_pixmap(pm)
        return True

    def _set_pixmap(self, pm: QPixmap) -> None:
        # Keep annotations? Generally, changing image means coords mismatch.
        # Policy: clear annotations on image set.
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pm)
        self._pixmap_item.setTransformationMode(Qt.SmoothTransformation)
        self._pixmap_item.setZValue(0)

        self._has_image = True
        self._scene.setSceneRect(QRectF(pm.rect()))
        self.resetTransform()
        self.fit_to_view()

        self._clear_annotations_internal(emit_signal=False)

    def fit_to_view(self) -> None:
        if not self._pixmap_item:
            self.resetTransform()
            return
        rect = self._pixmap_item.boundingRect()
        if rect.isNull():
            return
        self.resetTransform()
        self.fitInView(rect, Qt.KeepAspectRatio)

    # ----- Zoom -----
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

    # ----- Drag & drop image file -----
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

    # ----- Annotation persistence -----
    def get_annotations(self) -> Annotations:
        return self._strokes

    def set_annotations(self, strokes: Annotations) -> None:
        # rebuild overlay items from strokes
        self._clear_annotations_internal(emit_signal=False)
        if not self._has_image:
            # still store strokes (optional), but no visual until image exists
            self._strokes = strokes or []
            return

        self._strokes = strokes or []
        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            path = QPainterPath(QPointF(stroke[0][0], stroke[0][1]))
            for pt in stroke[1:]:
                path.lineTo(QPointF(pt[0], pt[1]))
            item = QGraphicsPathItem(path)
            item.setPen(self._pen)
            item.setZValue(10)
            self._scene.addItem(item)
            self._stroke_items.append(item)

    def clear_annotations(self) -> None:
        self._clear_annotations_internal(emit_signal=True)

    def _clear_annotations_internal(self, emit_signal: bool) -> None:
        # remove drawn items only
        for it in self._stroke_items:
            self._scene.removeItem(it)
        self._stroke_items = []
        self._strokes = []
        self._is_drawing = False
        self._current_item = None
        self._current_path = None
        self._current_points = []
        if emit_signal:
            self.annotationsChanged.emit()

    # ----- Drawing interactions -----
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
                # allow drawing to edge; clamp is optional. We'll just ignore moves outside.
                return
            self._append_stroke(scene_pos)
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
        self._current_path = QPainterPath(pt)
        self._current_points = [[float(pt.x()), float(pt.y())]]

        item = QGraphicsPathItem(self._current_path)
        item.setPen(self._pen)
        item.setZValue(10)
        self._scene.addItem(item)

        self._current_item = item

    def _append_stroke(self, pt: QPointF) -> None:
        if not self._current_path or not self._current_item:
            return

        # simple smoothing: ignore very small moves
        last = self._current_points[-1]
        dx = pt.x() - last[0]
        dy = pt.y() - last[1]
        if (dx * dx + dy * dy) < 4.0:  # ~2px threshold
            return

        self._current_path.lineTo(pt)
        self._current_item.setPath(self._current_path)
        self._current_points.append([float(pt.x()), float(pt.y())])

    def _finish_stroke(self) -> None:
        if not self._current_item or len(self._current_points) < 2:
            # discard
            if self._current_item:
                self._scene.removeItem(self._current_item)
            self._is_drawing = False
            self._current_item = None
            self._current_path = None
            self._current_points = []
            return

        # commit stroke
        self._stroke_items.append(self._current_item)
        self._strokes.append(self._current_points)

        # reset current
        self._is_drawing = False
        self._current_item = None
        self._current_path = None
        self._current_points = []

        self.annotationsChanged.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1320, 860)

        self.db = NoteDB(DEFAULT_DB_PATH)

        self.current_step_id: Optional[str] = None
        self.current_page_index: int = 0
        self._loading_ui: bool = False

        # Debounced autosave for page fields
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_page_fields_to_model_and_save)

        self._build_ui()
        self._load_ui_state_or_defaults()
        self._refresh_steps_list(select_current=True)
        self._load_current_page_to_ui()

        # Shortcuts
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_prev_page)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.go_next_page)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_page)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.force_save)

        # Ctrl+V for clipboard image paste ONLY when image area is focused (avoid breaking text paste)
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

        # Left: steps list
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

        # Right: page meta + content + navigator
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        # Meta bar (per page): Stock Name + Ticker + Copy
        meta_bar = QHBoxLayout()
        meta_bar.setContentsMargins(0, 0, 0, 0)

        meta_bar.addWidget(QLabel("Name:"))
        self.edit_stock_name = QLineEdit()
        self.edit_stock_name.setPlaceholderText("e.g., Apple Inc.")
        self.edit_stock_name.textChanged.connect(self._on_page_field_changed)
        meta_bar.addWidget(self.edit_stock_name, 3)

        meta_bar.addSpacing(12)
        meta_bar.addWidget(QLabel("Ticker:"))
        self.edit_ticker = QLineEdit()
        self.edit_ticker.setPlaceholderText("e.g., AAPL")
        self.edit_ticker.textChanged.connect(self._on_page_field_changed)
        meta_bar.addWidget(self.edit_ticker, 1)

        self.btn_copy_ticker = QPushButton("Copy Ticker")
        self.btn_copy_ticker.clicked.connect(self.copy_ticker)
        meta_bar.addWidget(self.btn_copy_ticker)

        meta_bar.addStretch(1)

        # Page split (image | text)
        self.page_splitter = QSplitter(Qt.Horizontal)

        # Image section
        img_container = QWidget()
        img_layout = QVBoxLayout(img_container)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(6)

        img_toolbar = QHBoxLayout()
        self.btn_set_image = QPushButton("Set Image...")
        self.btn_paste_image = QPushButton("Paste Image (Ctrl+V)")
        self.btn_clear_image = QPushButton("Clear Image")
        self.btn_reset_view = QPushButton("Reset View")

        self.btn_draw_mode = QToolButton()
        self.btn_draw_mode.setText("Draw")
        self.btn_draw_mode.setCheckable(True)
        self.btn_draw_mode.setToolTip("Toggle draw mode (draw lines on top of image)")
        self.btn_clear_lines = QPushButton("Clear Lines")

        self.btn_set_image.clicked.connect(self.set_image_via_dialog)
        self.btn_paste_image.clicked.connect(self.paste_image_from_clipboard)
        self.btn_clear_image.clicked.connect(self.clear_image)
        self.btn_reset_view.clicked.connect(self.reset_image_view)

        self.btn_draw_mode.toggled.connect(self.toggle_draw_mode)
        self.btn_clear_lines.clicked.connect(self.clear_lines)

        img_toolbar.addWidget(self.btn_set_image)
        img_toolbar.addWidget(self.btn_paste_image)
        img_toolbar.addWidget(self.btn_clear_image)
        img_toolbar.addWidget(self.btn_reset_view)
        img_toolbar.addSpacing(10)
        img_toolbar.addWidget(self.btn_draw_mode)
        img_toolbar.addWidget(self.btn_clear_lines)
        img_toolbar.addStretch(1)

        self.image_viewer = ZoomPanAnnotateView()
        self.image_viewer.imageDropped.connect(self._on_image_dropped)
        self.image_viewer.annotationsChanged.connect(self._on_page_field_changed)

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
        self.text_edit.textChanged.connect(self._on_page_field_changed)

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

        # Assemble right layout
        right_layout.addLayout(meta_bar)
        right_layout.addWidget(self.page_splitter, 1)
        right_layout.addLayout(nav)

        # Main splitter
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([270, 1050])

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

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

    # ---------------- Steps list ----------------
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

        self._flush_page_fields_to_model_and_save()

        step_id = item.data(Qt.UserRole)
        if not step_id:
            return

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
                self.text_edit.clear()
                self.image_viewer.clear_image()
                self.btn_draw_mode.setChecked(False)
                self._update_nav()
            finally:
                self._loading_ui = False
            return

        self._loading_ui = True
        try:
            # Meta
            self.edit_stock_name.setText(pg.stock_name or "")
            self.edit_ticker.setText(pg.ticker or "")

            # Image
            if pg.image_path:
                abs_path = _abspath_from_rel(pg.image_path)
                if os.path.exists(abs_path):
                    self.image_viewer.set_image_path(abs_path)
                else:
                    self.image_viewer.clear_image()
            else:
                self.image_viewer.clear_image()

            # Load annotations after image load (scene exists)
            self.image_viewer.set_annotations(pg.annotations or [])

            # Text
            self.text_edit.setPlainText(pg.note_text or "")

            # Default mode: Pan
            self.btn_draw_mode.setChecked(False)
            self.image_viewer.set_mode_pan()

            self._update_nav()
        finally:
            self._loading_ui = False

    def _on_page_field_changed(self) -> None:
        if self._loading_ui:
            return
        self._save_timer.start(450)

    def _flush_page_fields_to_model_and_save(self) -> None:
        st = self.current_step()
        pg = self.current_page()
        if not st or not pg:
            return
        if self._loading_ui:
            return

        changed = False

        # Text
        new_text = self.text_edit.toPlainText()
        if pg.note_text != new_text:
            pg.note_text = new_text
            changed = True

        # Meta
        new_name = self.edit_stock_name.text()
        if pg.stock_name != new_name:
            pg.stock_name = new_name
            changed = True

        new_ticker = self.edit_ticker.text()
        if pg.ticker != new_ticker:
            pg.ticker = new_ticker
            changed = True

        # Annotations
        new_anns = self.image_viewer.get_annotations()
        if pg.annotations != new_anns:
            pg.annotations = new_anns
            changed = True

        # Track last visited page for this step
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

        insert_at = self.current_page_index + 1  # policy: insert after current page
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
            "Delete current page?\n(This cannot be undone in v0.1.x.)",
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
        self.image_viewer.clear_annotations()
        # autosave debounced via annotationsChanged, but keep immediate save safer
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
        pg.annotations = []
        pg.updated_at = _now_epoch()
        self.db.save()
        self.image_viewer.clear_image()

    def paste_image_from_clipboard(self) -> None:
        """
        Paste image from clipboard and save it into ./assets, then set to current page.
        Shortcut Ctrl+V is bound to the image view only to avoid breaking text paste behavior.
        """
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
        pg.annotations = []  # new image => clear annotations (coords mismatch)
        pg.updated_at = _now_epoch()
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self.db.save()

        self.image_viewer.set_image_path(dst_abs)
        self.image_viewer.set_annotations([])
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
        pg.annotations = []  # new image => clear annotations (coords mismatch)
        pg.updated_at = _now_epoch()
        st.last_page_index = self.current_page_index
        self._save_ui_state()
        self.db.save()

        self.image_viewer.set_image_path(dst_abs)
        self.image_viewer.set_annotations([])
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
    def add_step(self) -> None:
        name, ok = QInputDialog.getText(self, "Add Step", "Step name:")
        if not ok or not name.strip():
            return
        self._flush_page_fields_to_model_and_save()
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
            f"Delete step '{st.name}' and all its pages?\n(This cannot be undone in v0.1.x.)",
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
