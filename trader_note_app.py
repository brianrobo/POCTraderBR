# -*- coding: utf-8 -*-
"""
Trader Chart Note App (PyQt5) - OneNote-style Step/Page Navigator

Version: 0.3.6  (2025-12-21)
Versioning: MAJOR.MINOR.PATCH (SemVer)

Release Notes (v0.3.6):
- (Safety) 중복 실행 방지(Single Instance Lock) 적용
  - data/trader_note_app.lock 파일 기반 QLockFile 사용
  - 이미 실행 중이면 안내 후 즉시 종료(저장 경합/WinError 5 확률 감소)
- (Recovery) Autosave 복구 UI 적용
  - 시작 시 data/notes_db.json.autosave.<timestamp>.json 검색
  - 최신 autosave가 본파일(notes_db.json)보다 “새로우면” 복구 여부 팝업
  - 복구 시 기존 notes_db.json은 notes_db.json.bak.<timestamp>.json 으로 백업
- (UX) Description(자유서술)에서 Bold(굵게) 강조 기능 추가
  - Bold 버튼 + Ctrl+B 단축키
  - Description은 Rich Text(HTML)로 저장/로드 (구버전 plain text도 자동 호환 로드)

Existing features (unchanged):
- Category → Step Tree(좌측), Category 우클릭 메뉴(카테고리 rename/delete/move up/down, 해당 카테고리에 step 추가)
- Category order JSON 저장(category_order)
- Step: add/rename/set category/delete
- Page: add/delete(confirm)/prev/next, step별 last_page_index 유지
- Image: Open / Paste(Clipboard) / Clear Image / Fit
- Viewer: Zoom wheel, Pan drag, Draw mode(shift 직선), pen color/width, Clear Lines(confirm)
- Page fields: stock name, ticker(복사 버튼), image caption overlay(멀티라인, hover/click 확장/축소)
- Description: checklist 4문항 + note, free text

Dependencies:
  pip install PyQt5

Run:
  python trader_note_app.py
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
    QLockFile,
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
    QTextCursor,
    QFont,
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
)

APP_TITLE = "Trader Chart Note (v0.3.6)"
DEFAULT_DB_PATH = os.path.join("data", "notes_db.json")
ASSETS_DIR = "assets"
LOCK_PATH = os.path.join("data", "trader_note_app.lock")

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


def _safe_write_json(path: str, data: Dict[str, Any], retries: int = 12, base_delay: float = 0.08) -> bool:
    """
    Atomic-ish JSON save for Windows.
    - Writes to .tmp then os.replace(tmp, path)
    - If destination is locked (PermissionError), retry with backoff
    - If still failing, writes autosave file and returns False (no crash)
    """
    _ensure_dir(os.path.dirname(path) or ".")
    tmp_path = f"{path}.tmp"

    # 1) write tmp
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        return False

    # 2) try replace with retry/backoff
    for i in range(max(1, retries)):
        try:
            os.replace(tmp_path, path)
            return True
        except PermissionError:
            time.sleep(base_delay * (1.6 ** i))
        except OSError:
            time.sleep(base_delay * (1.6 ** i))

    # 3) fallback: autosave
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


def _looks_like_html(text: str) -> bool:
    if not text:
        return False
    t = text.lstrip().lower()
    return t.startswith("<!doctype html") or t.startswith("<html") or "<body" in t or "<p" in t or "<span" in t


def _parse_autosave_ts(fname: str) -> Optional[int]:
    # notes_db.json.autosave.<epoch>.json
    m = re.search(r"\.autosave\.(\d+)\.json$", fname)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _find_latest_autosave(db_path: str) -> Optional[str]:
    d = os.path.dirname(db_path) or "."
    base = os.path.basename(db_path)
    prefix = f"{base}.autosave."
    if not os.path.isdir(d):
        return None

    best: Tuple[int, str] = (-1, "")
    for name in os.listdir(d):
        if not name.startswith(prefix) or not name.endswith(".json"):
            continue
        ts = _parse_autosave_ts(name)
        if ts is None:
            continue
        full = os.path.join(d, name)
        if os.path.isfile(full) and ts > best[0]:
            best = (ts, full)

    return best[1] if best[0] >= 0 else None


def _file_mtime(path: str) -> int:
    try:
        return int(os.path.getmtime(path))
    except Exception:
        return 0


def _maybe_recover_autosave(db_path: str, parent=None) -> None:
    """
    Startup recovery UI:
    - If a latest autosave exists and it's newer than the main db file (by timestamp in filename or mtime),
      prompt user to restore.
    - Restore = backup current db to .bak.<epoch>.json and replace with autosave.
    """
    autosave = _find_latest_autosave(db_path)
    if not autosave:
        return

    autosave_ts = _parse_autosave_ts(os.path.basename(autosave)) or _file_mtime(autosave)
    db_exists = os.path.exists(db_path)
    db_mtime = _file_mtime(db_path) if db_exists else 0

    # Trigger condition: autosave is "meaningfully" newer
    if db_exists and autosave_ts <= db_mtime:
        return

    msg = QMessageBox(parent)
    msg.setWindowTitle("Autosave Recovery")
    if db_exists:
        msg.setText("최신 autosave 파일이 notes_db.json 보다 새로 보입니다.\n복구를 진행할까요?")
    else:
        msg.setText("notes_db.json 파일이 없고 autosave 파일이 발견되었습니다.\n복구를 진행할까요?")

    msg.setInformativeText(
        f"- Latest autosave:\n  {autosave}\n\n"
        f"- notes_db.json:\n  {db_path if db_exists else '(missing)'}\n\n"
        "복구를 선택하면:\n"
        "- 기존 notes_db.json(있다면)은 notes_db.json.bak.<timestamp>.json 으로 백업\n"
        "- autosave 파일로 notes_db.json을 복원합니다."
    )

    btn_restore = msg.addButton("Restore", QMessageBox.AcceptRole)
    btn_ignore = msg.addButton("Ignore", QMessageBox.RejectRole)
    msg.setDefaultButton(btn_restore)
    msg.exec_()

    if msg.clickedButton() != btn_restore:
        return

    # Backup existing db
    try:
        if db_exists:
            bak_path = f"{db_path}.bak.{_now_epoch()}.json"
            shutil.copy2(db_path, bak_path)
    except Exception as e:
        QMessageBox.warning(parent, "Backup warning", f"기존 DB 백업 중 문제가 발생했습니다:\n{e}\n\n복구는 계속 진행합니다.")

    # Restore autosave -> db
    try:
        # use replace for atomic-ish behavior
        # if replace fails (rare at startup), fallback to copy2
        try:
            os.replace(autosave, db_path)
        except Exception:
            shutil.copy2(autosave, db_path)

        QMessageBox.information(parent, "Recovered", "Autosave 복구가 완료되었습니다.\n앱을 계속 실행합니다.")
    except Exception as e:
        QMessageBox.critical(parent, "Recovery failed", f"Autosave 복구에 실패했습니다:\n{e}\n\n복구 없이 계속 진행합니다.")


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

    def addWidget(self, w: QWidget) -> None:
        self.addItem(QWidgetItem(w))

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
# Collapsible caption overlay (1-line collapsed, expands on hover/focus)
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
    image_caption: str
    note_text: str  # v0.3.6+: HTML (rich text). legacy plain text supported.
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
        self.category_order: List[str] = []
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

        raw_order = self.data.get("category_order", [])
        if isinstance(raw_order, list):
            self.category_order = [str(x).strip() for x in raw_order if str(x).strip()]
        else:
            self.category_order = []

        self._ensure_category_order_consistency()

    def save(self) -> bool:
        self.data["version"] = "0.3.6"
        self.data["updated_at"] = _now_epoch()
        self.data["steps"] = self._serialize_steps(self.steps)
        self.data["ui_state"] = self.ui_state
        self.data["category_order"] = self.category_order

        ok = _safe_write_json(self.db_path, self.data)
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
                            "image_path": "",
                            "image_caption": "",
                            "note_text": "",  # legacy plain text, but ok
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
            "version": "0.3.6",
            "created_at": _now_epoch(),
            "updated_at": _now_epoch(),
            "steps": steps,
            "ui_state": {},
            "category_order": ["General"],
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
                        image_caption=str(p.get("image_caption", "")),
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
                            "image_caption": pg.image_caption,
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
            image_caption="",
            note_text="",
            stock_name="",
            ticker="",
            strokes=[],
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
        for it in list(self._stroke_items):
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
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
        self.resize(1400, 930)

        self.db = NoteDB(DEFAULT_DB_PATH)

        self.current_step_id: Optional[str] = None
        self.current_page_index: int = 0
        self._loading_ui: bool = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._flush_page_fields_to_model_and_save)

        # 저장 실패 경고 스팸 방지
        self._last_save_warn_ts: float = 0.0
        self._save_warn_cooldown_sec: float = 10.0

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

        # Bold shortcut (Description)
        QShortcut(QKeySequence("Ctrl+B"), self.text_edit, activated=self._toggle_bold_shortcut)

    def closeEvent(self, event) -> None:
        try:
            self._flush_page_fields_to_model_and_save()
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

        self.steps_tree = QTreeWidget()
        self.steps_tree.setHeaderHidden(True)
        self.steps_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.steps_tree.setUniformRowHeights(True)

        self.steps_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.steps_tree.customContextMenuRequested.connect(self._on_tree_context_menu)

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
        self.image_viewer.viewport().installEventFilter(self)

        # Navigator
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

        # Header row + format tools
        text_header = QWidget()
        text_header_flow = FlowLayout(text_header, margin=0, spacing=6)

        self.text_title = QLabel("Description")
        self.btn_clear_text = QPushButton("Clear Text")
        self.btn_clear_text.clicked.connect(self.clear_text)

        self.btn_bold = QToolButton()
        self.btn_bold.setText("B")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setToolTip("Bold (Ctrl+B)")
        self.btn_bold.setStyleSheet("QToolButton{font-weight:700; padding:2px 10px;}")
        self.btn_bold.toggled.connect(self._toggle_bold)

        text_header_flow.addWidget(self.text_title)
        text_header_flow.addWidget(QLabel("Format:"))
        text_header_flow.addWidget(self.btn_bold)
        text_header_flow.addWidget(self.btn_clear_text)

        self.text_edit = QTextEdit()
        self.text_edit.setAcceptRichText(True)
        self.text_edit.setPlaceholderText("추가 분석/설명을 자유롭게 작성하세요... (굵게: Ctrl+B)")
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
        main_splitter.setSizes([340, 1060])

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(main_splitter)

    # ---------------- Bold formatting helpers ----------------
    def _toggle_bold_shortcut(self) -> None:
        # mirror button state so UI stays coherent
        self.btn_bold.setChecked(not self.btn_bold.isChecked())

    def _toggle_bold(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold if checked else QFont.Normal)

        cursor = self.text_edit.textCursor()
        if cursor is None:
            return

        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
            self.text_edit.setTextCursor(cursor)
        else:
            self.text_edit.mergeCurrentCharFormat(fmt)

        self.text_edit.setFocus(Qt.ShortcutFocusReason)

    # ---------------- Tree context menu (Category) ----------------
    def _on_tree_context_menu(self, pos) -> None:
        item = self.steps_tree.itemAt(pos)
        if not item:
            return

        node_type = item.data(0, self.NODE_TYPE_ROLE)
        if node_type != "category":
            return

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

    # ---------------- Annotate Overlay + Caption Overlay ----------------
    def _build_annotate_overlay(self) -> None:
        vp = self.image_viewer.viewport()

        self.edit_img_caption = CollapsibleCaptionEdit(vp, collapsed_h=28, expanded_h=84)
        self.edit_img_caption.setPlaceholderTextCompat("이미지 간단 설명 (hover/클릭 시 2~3줄 확장)")
        self.edit_img_caption.textChanged.connect(self._on_page_field_changed)
        self.edit_img_caption.expandedChanged.connect(lambda _: self._reposition_overlay())

        self.btn_anno_toggle = QToolButton(vp)
        self.btn_anno_toggle.setText("✎")
        self.btn_anno_toggle.setToolTip("Open Annotate panel")
        self.btn_anno_toggle.setAutoRaise(True)
        self.btn_anno_toggle.setFixedSize(34, 30)
        self.btn_anno_toggle.clicked.connect(self._open_annotate_panel)

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

        self.btn_draw_mode = QToolButton(self.anno_panel)
        self.btn_draw_mode.setText("Draw")
        self.btn_draw_mode.setCheckable(True)
        self.btn_draw_mode.setToolTip("Toggle draw mode. Drag to draw. Hold SHIFT for straight line.")
        self.btn_draw_mode.toggled.connect(self.toggle_draw_mode)
        p_layout.addWidget(self.btn_draw_mode)

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

        self.btn_clear_lines = QPushButton("Clear Lines", self.anno_panel)
        self.btn_clear_lines.clicked.connect(self.clear_lines)
        p_layout.addWidget(self.btn_clear_lines)

        help_lbl = QLabel(
            "• Wheel: Zoom\n"
            "• Drag: Pan (Draw OFF)\n"
            "• Drag: Draw (Draw ON)\n"
            "• Shift+Drag: Straight line\n"
            "• Ctrl+V: Paste image (when viewer focused)\n"
            "• Alt+←/→: Prev/Next\n"
            "• Ctrl+N: Add page, Ctrl+S: Save\n"
            "• Ctrl+B: Bold (Description)",
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

        self.btn_anno_toggle.move(max(margin, w - self.btn_anno_toggle.width() - margin), margin)

        cap_min = 260
        cap_max = 720
        btn_w = self.btn_anno_toggle.width()

        if self.anno_panel.isVisible():
            panel_x = max(margin, w - self.anno_panel.width() - margin)
            self.anno_panel.move(panel_x, margin)

            cap_w = min(cap_max, max(cap_min, panel_x - 2 * margin))
            cap_x = max(margin, panel_x - margin - cap_w)
        else:
            cap_w = min(cap_max, max(cap_min, w - (btn_w + 3 * margin)))
            cap_x = max(margin, w - margin - btn_w - margin - cap_w)

        self.edit_img_caption.setFixedWidth(cap_w)
        self.edit_img_caption.move(cap_x, margin)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.image_viewer.viewport() and event.type() == QEvent.Resize:
            self._reposition_overlay()
        return super().eventFilter(obj, event)

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

        cats = self.db.list_categories()
        cat_nodes: Dict[str, QTreeWidgetItem] = {}

        for cat in cats:
            top = QTreeWidgetItem([cat])
            top.setData(0, self.NODE_TYPE_ROLE, "category")
            top.setData(0, self.CATEGORY_NAME_ROLE, cat)
            top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
            self.steps_tree.addTopLevelItem(top)
            cat_nodes[cat] = top

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
                "- 앱이 2개 실행 중인지 확인(현재 버전은 중복 실행을 차단합니다)\n"
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
                self.edit_img_caption.setPlainText("")
                for cb in self.chk_boxes:
                    cb.setChecked(False)
                for note in self.chk_notes:
                    note.clear()
                self.text_edit.clear()
                self.image_viewer.clear_image()
                self.btn_draw_mode.setChecked(False)
                self.btn_bold.setChecked(False)
                self._update_nav()
            finally:
                self._loading_ui = False
            return

        self._loading_ui = True
        try:
            self.edit_stock_name.setText(pg.stock_name or "")
            self.edit_ticker.setText(pg.ticker or "")
            self.edit_img_caption.setPlainText(pg.image_caption or "")

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

            # v0.3.6: RichText(HTML) load with legacy fallback
            if _looks_like_html(pg.note_text):
                self.text_edit.setHtml(pg.note_text or "")
            else:
                self.text_edit.setPlainText(pg.note_text or "")

            self.btn_draw_mode.setChecked(False)
            self.image_viewer.set_mode_pan()
            self.btn_bold.setChecked(False)

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

        new_cap = self.edit_img_caption.toPlainText()
        if pg.image_caption != new_cap:
            pg.image_caption = new_cap
            changed = True

        # v0.3.6: store HTML for Description
        new_text_html = self.text_edit.toHtml()
        if pg.note_text != new_text_html:
            pg.note_text = new_text_html
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
        self._save_db_with_warning()
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
        self._save_db_with_warning()
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
        self._save_db_with_warning()

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
        self._save_db_with_warning()

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


def _acquire_single_instance_lock(app: QApplication) -> Optional[QLockFile]:
    """
    Single instance lock using QLockFile.
    Keep returned lock object alive for the entire app lifetime.
    """
    _ensure_dir(os.path.dirname(LOCK_PATH) or ".")
    lock = QLockFile(LOCK_PATH)
    lock.setStaleLockTime(0)  # do not auto-break; be conservative on Windows
    ok = lock.tryLock(50)
    if ok:
        return lock

    QMessageBox.critical(
        None,
        "Already running",
        "이미 실행 중인 Trader Chart Note App 인스턴스가 있습니다.\n\n"
        "중복 실행은 notes_db.json 저장 경합(WinError 5)을 유발할 수 있어 차단되었습니다.\n"
        "기존 앱을 종료한 뒤 다시 실행해 주세요."
    )
    return None


def main() -> None:
    _ensure_dir("data")
    _ensure_dir(ASSETS_DIR)

    app = QApplication(sys.argv)

    # 1) single instance
    lock = _acquire_single_instance_lock(app)
    if lock is None:
        sys.exit(0)
    app._instance_lock = lock  # keep alive

    # 2) autosave recovery UI (before DB load)
    _maybe_recover_autosave(DEFAULT_DB_PATH, parent=None)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
