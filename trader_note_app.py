# -*- coding: utf-8 -*-
"""
Trader Chart Note App (PyQt5) - Folder(Item) Navigator

Version: 0.10.3  (2026-01-01)

v0.10.3 변경 사항:
- Global Ideas 탭 이름 변경 기능
  AS-IS: 탭 이름이 "Ideas 1", "Ideas 2" 등 고정된 형식
  TO-BE:
    - 탭 더블 클릭 시 이름 변경 다이얼로그 표시
    - 사용자가 원하는 이름으로 탭 제목 지정 가능
    - 변경된 이름이 자동으로 저장되어 앱 재시작 시에도 유지
- 최근 작업 리스트 기능
  AS-IS: 최근 작업한 item을 확인할 방법 없음
  TO-BE:
    - 좌측 네비게이션 트리 아래에 "최근 작업" 섹션 추가
    - 최근 10개 item을 최신 순으로 표시
    - 각 item에 카테고리 경로와 상대 시간 표시 (방금 전, 2시간 전, 어제 등)
    - 클릭 시 해당 item으로 자동 이동 및 부모 폴더 자동 확장
    - Item에 `last_accessed_at` 필드 추가하여 접근 시간 추적
- 폴더 URL 링크 기능
  AS-IS: 폴더에 관련 URL 정보를 저장할 방법 없음
  TO-BE:
    - Category에 `url` 필드 추가
    - 우클릭 메뉴에 "Set URL..." / "Edit URL..." / "Open URL" / "Remove URL" 항목 추가
    - URL이 있는 폴더는 이름 뒤에 🔗 이모지 및 파란색으로 표시
    - 마우스 오버 시 툴팁에 URL 표시
    - URL 클릭 시 기본 브라우저로 자동 열기
- Global Ideas 자동 백업 기능
  AS-IS: Global Ideas 내용 삭제/변경 시 복구 불가능
  TO-BE:
    - Global Ideas 변경 감지 시 자동 백업 생성
    - `data/backups/global_ideas_backup_<timestamp>.json` 형식으로 저장
    - 최근 20개 백업 파일만 유지 (자동 정리)
    - 기존 DB 백업 시스템과 독립적으로 동작
    - 백업 실패해도 저장은 계속 진행

v0.10.2 변경 사항:
- 트리 확장/축소 상태 저장 및 복원 기능
  AS-IS: 앱 재시작 시 트리 확장 상태가 초기화됨
  TO-BE:
    - 트리 확장/축소 시 자동으로 상태 저장
    - 앱 재시작 시 이전 확장 상태 자동 복원
    - `ui_state["tree_expanded_categories"]`에 확장된 카테고리 ID 목록 저장
- ROOT 폴더 보호 강화
  AS-IS: ROOT 폴더가 UI에서만 삭제/이름 변경 방지
  TO-BE:
    - ROOT 폴더 고정 ID (`__ROOT__`) 사용
    - 모든 삭제 경로에서 ROOT 폴더 보호 (방어적 프로그래밍)
    - ROOT 폴더는 항상 첫 번째로 표시
- 더블 클릭 크래시 수정 및 예외 처리 강화
  AS-IS: 트리 아이템 더블 클릭 시 크래시 발생
  TO-BE:
    - 더블 클릭 이벤트 핸들러 추가 (`_on_tree_item_double_clicked`)
    - 선택 변경 이벤트에 예외 처리 추가
    - 아이템 페이지가 없는 경우 자동 생성
- 폴더 확장/축소 기능 개선
  AS-IS: 폴더 클릭/더블 클릭 시 확장/축소가 동작하지 않음
  TO-BE:
    - `ExpandableTreeWidget` 커스텀 클래스 추가
    - 아이콘 영역(왼쪽 20px) 클릭 시 확장/축소
    - 단일 클릭 및 더블 클릭 모두 지원
"""

import json
import os
import re
import shutil
import sys
import time
import uuid
import zipfile
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QPointF, QRect, QPoint, QEvent, QSize, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtGui import (
    QImage, QPixmap, QPainterPath, QPen, QColor, QPainter, QIcon,
    QTextCharFormat, QTextListFormat, QTextBlockFormat, QTextCursor, QFont, QBrush, QKeySequence
)
from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QGraphicsPixmapItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QShortcut, QSplitter, QTextEdit, QToolButton,
    QVBoxLayout, QHBoxLayout, QWidget, QInputDialog, QComboBox, QCheckBox, QGroupBox, QPushButton,
    QLayout, QWidgetItem, QFrame, QTreeWidget, QTreeWidgetItem, QMenu, QPlainTextEdit,
    QAbstractItemView, QButtonGroup, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QSplitterHandle, QTabWidget, QScrollArea, QListWidget, QListWidgetItem
)

APP_TITLE = "Trader Chart Note (v0.10.3)"
DEFAULT_DB_PATH = os.path.join("data", "notes_db.json")
BACKUP_DIR = os.path.join("data", "backups")
MAX_BACKUPS = 10  # 최대 백업 파일 개수
MAX_IDEAS_BACKUPS = 20  # Global Ideas 최대 백업 파일 개수
MAX_DATA_SIZE_MB = 50  # 최대 데이터 크기 (MB)
ASSETS_DIR = "assets"
ROOT_CATEGORY_ID = "__ROOT__"  # ROOT 폴더 고정 ID (삭제 불가)

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


def _format_relative_time(timestamp: int) -> str:
    """상대 시간 포맷팅 (예: "방금 전", "2시간 전", "어제", "2025-01-01")"""
    if timestamp <= 0:
        return "없음"
    
    now = _now_epoch()
    diff = now - timestamp
    
    if diff < 60:
        return "방금 전"
    elif diff < 3600:
        minutes = diff // 60
        return f"{minutes}분 전"
    elif diff < 86400:
        hours = diff // 3600
        return f"{hours}시간 전"
    elif diff < 172800:  # 2일 미만
        return "어제"
    else:
        # 날짜 형식으로 표시
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _validate_json_serializable(data: Any) -> Tuple[bool, Optional[str]]:
    """JSON 직렬화 가능 여부 검증"""
    try:
        json.dumps(data, ensure_ascii=False, default=str)
        return True, None
    except (TypeError, ValueError) as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def _create_backup(db_path: str) -> Optional[str]:
    """저장 전 백업 생성"""
    if not os.path.exists(db_path):
        return None
    
    try:
        _ensure_dir(BACKUP_DIR)
        timestamp = _now_epoch()
        backup_filename = f"notes_db_backup_{timestamp}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        
        # 기존 파일 복사
        shutil.copy2(db_path, backup_path)
        
        # 오래된 백업 파일 정리
        _cleanup_old_backups()
        
        return backup_path
    except Exception as e:
        # 백업 실패해도 저장은 계속 진행
        return None


def _cleanup_old_backups() -> None:
    """오래된 백업 파일 정리 (최근 MAX_BACKUPS개만 유지)"""
    try:
        if not os.path.exists(BACKUP_DIR):
            return
        
        backup_files = []
        for filename in os.listdir(BACKUP_DIR):
            if filename.startswith("notes_db_backup_") and filename.endswith(".json"):
                filepath = os.path.join(BACKUP_DIR, filename)
                try:
                    mtime = os.path.getmtime(filepath)
                    backup_files.append((mtime, filepath))
                except Exception:
                    continue
        
        # 최신순으로 정렬
        backup_files.sort(reverse=True)
        
        # MAX_BACKUPS개 초과 시 오래된 것 삭제
        for mtime, filepath in backup_files[MAX_BACKUPS:]:
            try:
                os.remove(filepath)
            except Exception:
                pass
    except Exception:
        pass


def _backup_global_ideas(ideas_data: List[Dict[str, str]]) -> Optional[str]:
    """Global Ideas 백업 생성"""
    if not ideas_data:
        return None
    
    try:
        _ensure_dir(BACKUP_DIR)
        timestamp = _now_epoch()
        backup_filename = f"global_ideas_backup_{timestamp}.json"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        
        # Global Ideas 데이터만 저장
        backup_data = {
            "timestamp": timestamp,
            "global_ideas": ideas_data.copy()
        }
        
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        
        # 오래된 Global Ideas 백업 파일 정리
        _cleanup_old_ideas_backups()
        
        return backup_path
    except Exception as e:
        # 백업 실패해도 저장은 계속 진행
        print(f"[DEBUG] Global Ideas 백업 실패: {str(e)}")
        return None


def _cleanup_old_ideas_backups() -> None:
    """오래된 Global Ideas 백업 파일 정리 (최근 MAX_IDEAS_BACKUPS개만 유지)"""
    try:
        if not os.path.exists(BACKUP_DIR):
            return
        
        backup_files = []
        for filename in os.listdir(BACKUP_DIR):
            if filename.startswith("global_ideas_backup_") and filename.endswith(".json"):
                filepath = os.path.join(BACKUP_DIR, filename)
                try:
                    mtime = os.path.getmtime(filepath)
                    backup_files.append((mtime, filepath))
                except Exception:
                    continue
        
        # 최신순으로 정렬
        backup_files.sort(reverse=True)
        
        # MAX_IDEAS_BACKUPS개 초과 시 오래된 것 삭제
        for mtime, filepath in backup_files[MAX_IDEAS_BACKUPS:]:
            try:
                os.remove(filepath)
            except Exception:
                pass
    except Exception:
        pass


def _check_data_size(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """데이터 크기 확인"""
    try:
        json_str = json.dumps(data, ensure_ascii=False, default=str)
        size_mb = len(json_str.encode('utf-8')) / (1024 * 1024)
        if size_mb > MAX_DATA_SIZE_MB:
            return False, f"Data size ({size_mb:.2f} MB) exceeds maximum ({MAX_DATA_SIZE_MB} MB)"
        return True, None
    except Exception as e:
        return False, f"Error checking data size: {str(e)}"


def _safe_write_json(path: str, data: Dict[str, Any], retries: int = 12, base_delay: float = 0.08, create_backup: bool = True) -> Tuple[bool, Optional[str]]:
    """
    안전한 JSON 파일 저장
    Returns: (success: bool, error_message: Optional[str])
    """
    # 1. JSON 직렬화 가능 여부 검증
    is_valid, error = _validate_json_serializable(data)
    if not is_valid:
        return False, f"Data is not JSON serializable: {error}"
    
    # 2. 데이터 크기 확인
    size_ok, size_error = _check_data_size(data)
    if not size_ok:
        return False, size_error
    
    # 3. 백업 생성 (기존 파일이 있는 경우)
    backup_path = None
    if create_backup and os.path.exists(path):
        backup_path = _create_backup(path)
    
    _ensure_dir(os.path.dirname(path) or ".")
    tmp_path = f"{path}.tmp"

    # 4. 임시 파일에 저장
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, f"Failed to write temporary file: {str(e)}"

    # 5. 원본 파일로 교체 (재시도)
    for i in range(max(1, retries)):
        try:
            os.replace(tmp_path, path)
            return True, None
        except PermissionError:
            if i < retries - 1:
                time.sleep(base_delay * (1.6 ** i))
            else:
                # 마지막 시도 실패 시 autosave 생성
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
                    return False, f"Permission denied after {retries} retries. Autosave created: {autosave_path}"
                except Exception as e:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    return False, f"Failed to create autosave: {str(e)}"
        except OSError as e:
            if i < retries - 1:
                time.sleep(base_delay * (1.6 ** i))
            else:
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
                    return False, f"OS error after {retries} retries: {str(e)}. Autosave created: {autosave_path}"
                except Exception as e2:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    return False, f"Failed to create autosave: {str(e2)}"

    # 6. 모든 재시도 실패 시 autosave 생성
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
        return False, f"Failed after {retries} retries. Autosave created: {autosave_path}"
    except Exception as e:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return False, f"Failed to create autosave: {str(e)}"


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
CustomChecklist = List[Dict[str, Any]]  # [{"q": str, "checked": bool, "note": str}, ...]


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


def _default_custom_checklist() -> CustomChecklist:
    return []


def _normalize_custom_checklist(raw: Any) -> CustomChecklist:
    """Custom Checklist 정규화"""
    if not isinstance(raw, list):
        return []
    out: CustomChecklist = []
    for item in raw:
        if isinstance(item, dict):
            out.append({
                "q": str(item.get("q", "")).strip() or "새 항목",
                "checked": bool(item.get("checked", False)),
                "note": str(item.get("note", "") or "")
            })
    return out


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
    custom_checklist: CustomChecklist
    created_at: int
    updated_at: int


@dataclass
class Item:
    id: str
    name: str
    category_id: str
    pages: List[Page]
    last_page_index: int = 0
    last_accessed_at: int = 0  # 마지막 접근 시간 (epoch timestamp)


@dataclass
class Category:
    id: str
    name: str
    parent_id: Optional[str]
    child_ids: List[str]
    item_ids: List[str]
    url: str = ""  # 폴더 관련 URL 링크


class NoteDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.data: Dict[str, Any] = {}
        self.categories: Dict[str, Category] = {}
        self.items: Dict[str, Item] = {}
        self.root_category_ids: List[str] = []
        self.ui_state: Dict[str, Any] = {}
        self.global_ideas: List[Dict[str, str]] = []  # [{"name": str, "content": str}, ...] 최대 10개
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
            custom_checklist=_default_custom_checklist(),
            created_at=now,
            updated_at=now,
        )

    def _default_data(self) -> Dict[str, Any]:
        now = _now_epoch()

        return {
            "version": "0.6.0",
            "created_at": now,
            "updated_at": now,
            "root_category_ids": [ROOT_CATEGORY_ID],
            "categories": [
                {"id": ROOT_CATEGORY_ID, "name": "ROOT", "parent_id": None, "child_ids": [], "item_ids": [], "url": ""}
            ],
            "items": [],
            "ui_state": {
                "selected_category_id": ROOT_CATEGORY_ID,
                "selected_item_id": "",
                "current_page_index": 0,
                "global_ideas_visible": False,
                "desc_visible": True,
                "page_splitter_sizes": None,
                "notes_splitter_sizes": None,
                "trace_visible": True,
                "right_vsplit_sizes": None,
            },
            "global_ideas": [],
        }

    def load(self) -> None:
        """데이터 로드 (에러 처리 및 복구 로직 포함)"""
        print(f"[DEBUG] load() 시작 - db_path: {self.db_path}, 존재: {os.path.exists(self.db_path)}")
        
        # 이전 형식 데이터가 있으면 초기화
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    temp_data = json.load(f)
                
                # 이전 형식("root" 객체)이면 초기화
                if isinstance(temp_data, dict) and "root" in temp_data:
                    print(f"[DEBUG] 이전 형식 데이터 감지 - 초기화")
                    self._initialize_db()
                    return
                
                # 현재 형식이면 정상 로드
                if isinstance(temp_data, dict) and "categories" in temp_data:
                    self.data = temp_data
                    print(f"[DEBUG] JSON 로드 성공 - categories: {len(self.data.get('categories', []))}, items: {len(self.data.get('items', []))}")
                else:
                    print(f"[DEBUG] 잘못된 형식 - 초기화")
                    self._initialize_db()
                    return
                    
            except json.JSONDecodeError as e:
                print(f"[DEBUG] JSON 파싱 오류: {str(e)} - 초기화")
                self._initialize_db()
                return
            except Exception as e:
                print(f"[DEBUG] 로드 오류: {str(e)} - 초기화")
                self._initialize_db()
                return
        else:
            print(f"[DEBUG] 파일 없음 - 초기화")
            self._initialize_db()
            return

        # 데이터 파싱
        self._parse_categories_items(self.data)
        print(f"[DEBUG] _parse_categories_items() 완료 - categories: {len(self.categories)}, items: {len(self.items)}, root_category_ids: {self.root_category_ids}")
        
        self._ensure_integrity()
        print(f"[DEBUG] _ensure_integrity() 완료 - root_category_ids: {self.root_category_ids}")
        
        # UI state 로드
        self.ui_state = self.data.get("ui_state", {})
        if not isinstance(self.ui_state, dict):
            self.ui_state = {}
        print(f"[DEBUG] ui_state 로드 완료 - tree_expanded_categories: {self.ui_state.get('tree_expanded_categories', [])}")
        
        # global_ideas 로드
        ideas_raw = self.data.get("global_ideas", [])
        if isinstance(ideas_raw, list):
            self.global_ideas = ideas_raw
        elif isinstance(ideas_raw, str):
            # 이전 형식 (문자열)이면 빈 리스트로 초기화
            self.global_ideas = []
        else:
            self.global_ideas = []
    
    def _initialize_db(self) -> None:
        """DB를 기본 데이터로 초기화"""
        print(f"[DEBUG] DB 초기화 시작")
        self.data = self._default_data()
        self._parse_categories_items(self.data)
        self._ensure_integrity()
        # 초기화 후 즉시 저장
        ok, error = self.save()
        if ok:
            print(f"[DEBUG] DB 초기화 및 저장 성공")
        else:
            print(f"[DEBUG] DB 초기화 후 저장 실패: {error}")
    
    def _try_restore_from_backup(self) -> bool:
        """백업 파일에서 데이터 복구 시도"""
        try:
            if not os.path.exists(BACKUP_DIR):
                return False
            
            # 최신 백업 파일 찾기
            backup_files = []
            for filename in os.listdir(BACKUP_DIR):
                if filename.startswith("notes_db_backup_") and filename.endswith(".json"):
                    filepath = os.path.join(BACKUP_DIR, filename)
                    try:
                        mtime = os.path.getmtime(filepath)
                        backup_files.append((mtime, filepath))
                    except Exception:
                        continue
            
            if not backup_files:
                return False
            
            # 최신 백업 파일로 복구 시도
            backup_files.sort(reverse=True)
            for mtime, backup_path in backup_files:
                try:
                    with open(backup_path, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                    if isinstance(self.data, dict):
                        # 백업 복구 성공: 원본 파일을 백업으로 교체
                        try:
                            shutil.copy2(backup_path, self.db_path)
                        except Exception:
                            pass
                        return True
                except Exception:
                    continue
            
            return False
        except Exception:
            return False


    def save(self) -> Tuple[bool, Optional[str]]:
        """
        데이터 저장
        Returns: (success: bool, error_message: Optional[str])
        """
        print(f"[DEBUG] save() 시작 - db_path: {self.db_path}")
        print(f"[DEBUG] 저장 전 상태 - categories: {len(self.categories)}, items: {len(self.items)}, root_category_ids: {len(self.root_category_ids)}")
        
        # 저장 전 데이터 정규화 및 무결성 검증
        self._ensure_integrity()
        print(f"[DEBUG] _ensure_integrity() 완료 - root_category_ids: {self.root_category_ids}")
        
        # self.data 초기화 (없으면 빈 dict로 시작)
        if not isinstance(self.data, dict):
            self.data = {}
        
        # 데이터 직렬화
        self.data["version"] = "0.6.0"
        if "created_at" not in self.data:
            self.data["created_at"] = _now_epoch()
        self.data["updated_at"] = _now_epoch()
        self.data["ui_state"] = self.ui_state.copy() if isinstance(self.ui_state, dict) else {}
        self.data["global_ideas"] = self.global_ideas.copy() if isinstance(self.global_ideas, list) else []
        self.data["root_category_ids"] = list(self.root_category_ids)
        print(f"[DEBUG] 기본 데이터 설정 완료 - root_category_ids: {self.data['root_category_ids']}")
        
        # 카테고리 및 아이템 직렬화 (예외 처리)
        try:
            category_ids = self._all_category_ids_in_stable_order()
            print(f"[DEBUG] 카테고리 직렬화 시작 - 개수: {len(category_ids)}")
            self.data["categories"] = [self._serialize_category(self.categories[cid]) for cid in category_ids]
            print(f"[DEBUG] 카테고리 직렬화 완료 - 저장된 개수: {len(self.data['categories'])}")
        except Exception as e:
            print(f"[DEBUG] 카테고리 직렬화 실패: {str(e)}")
            return False, f"Failed to serialize categories: {str(e)}"
        
        try:
            item_ids = self._all_item_ids_in_stable_order()
            print(f"[DEBUG] 아이템 직렬화 시작 - 개수: {len(item_ids)}")
            self.data["items"] = [self._serialize_item(self.items[iid]) for iid in item_ids]
            print(f"[DEBUG] 아이템 직렬화 완료 - 저장된 개수: {len(self.data['items'])}")
        except Exception as e:
            print(f"[DEBUG] 아이템 직렬화 실패: {str(e)}")
            return False, f"Failed to serialize items: {str(e)}"
        
        # 안전한 저장 (백업 포함)
        print(f"[DEBUG] _safe_write_json() 호출 시작")
        result = _safe_write_json(self.db_path, self.data, create_backup=True)
        if result[0]:
            print(f"[DEBUG] 저장 성공!")
        else:
            print(f"[DEBUG] 저장 실패: {result[1]}")
        return result

    def _parse_categories_items(self, raw: Dict[str, Any]) -> None:
        """카테고리와 아이템 파싱 (현재 형식만 지원)"""
        self.categories = {}
        self.items = {}
        self.root_category_ids = []
        
        print(f"[DEBUG] _parse_categories_items() 시작 - raw keys: {list(raw.keys())}")

        root_ids = raw.get("root_category_ids", [])
        print(f"[DEBUG] _parse_categories_items() 시작 - root_ids from data: {root_ids}")
        if isinstance(root_ids, list):
            self.root_category_ids = [str(x) for x in root_ids if str(x)]
        else:
            self.root_category_ids = []
        print(f"[DEBUG] root_category_ids 파싱 완료: {self.root_category_ids}")

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
                    url = str(c.get("url", "")).strip() or ""
                    self.categories[cid] = Category(
                        id=cid, name=name, parent_id=parent_id,
                        child_ids=[str(x) for x in child_ids if str(x)],
                        item_ids=[str(x) for x in item_ids if str(x)],
                        url=url,
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
                                    custom_checklist=_normalize_custom_checklist(p.get("custom_checklist", None)),
                                    created_at=int(p.get("created_at", _now_epoch())),
                                    updated_at=int(p.get("updated_at", _now_epoch())),
                                )
                            )
                    if not pages:
                        pages = [self.new_page()]

                    last_accessed_at = int(it.get("last_accessed_at", 0))
                    self.items[iid] = Item(
                        id=iid, name=name, category_id=cat_id, pages=pages, 
                        last_page_index=last_page_index, last_accessed_at=last_accessed_at
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
            "custom_checklist": pg.custom_checklist,
            "created_at": pg.created_at,
            "updated_at": pg.updated_at,
        }

    def _serialize_item(self, it: Item) -> Dict[str, Any]:
        return {
            "id": it.id,
            "name": it.name,
            "category_id": it.category_id,
            "last_page_index": it.last_page_index,
            "last_accessed_at": it.last_accessed_at,
            "pages": [self._serialize_page(p) for p in it.pages],
        }

    def _serialize_category(self, c: Category) -> Dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "child_ids": list(c.child_ids),
            "item_ids": list(c.item_ids),
            "url": c.url,
        }

    def _migrate_old_format(self, old_data: Dict[str, Any]) -> Dict[str, Any]:
        """이전 형식(중첩 구조)을 현재 형식(평면 구조)으로 마이그레이션"""
        new_data = {
            "version": old_data.get("version", "0.6.0"),
            "created_at": old_data.get("created_at", _now_epoch()),
            "updated_at": old_data.get("updated_at", _now_epoch()),
            "root_category_ids": [],
            "categories": [],
            "items": [],
            "ui_state": old_data.get("ui_state", {}),
            "global_ideas": old_data.get("global_ideas", []),
        }
        
        def extract_categories(cat_obj: Dict[str, Any], parent_id: Optional[str] = None) -> None:
            """재귀적으로 카테고리 추출"""
            cid = str(cat_obj.get("id", _uuid()))
            name = str(cat_obj.get("name", "Folder")).strip() or "Folder"
            
            # 카테고리 추가
            new_cat = {
                "id": cid,
                "name": name,
                "parent_id": parent_id,
                "child_ids": [],
                "item_ids": [],
            }
            new_data["categories"].append(new_cat)
            
            # root 카테고리인 경우 root_category_ids에 추가
            if parent_id is None:
                new_data["root_category_ids"].append(cid)
            
            # 자식 카테고리 처리
            child_cats = cat_obj.get("categories", [])
            if isinstance(child_cats, list):
                for child_cat in child_cats:
                    child_id = str(child_cat.get("id", _uuid()))
                    new_cat["child_ids"].append(child_id)
                    extract_categories(child_cat, parent_id=cid)
            
            # 아이템 처리
            items = cat_obj.get("items", [])
            if isinstance(items, list):
                for item in items:
                    iid = str(item.get("id", _uuid()))
                    new_cat["item_ids"].append(iid)
                    
                    # 아이템 추가 (category_id 설정)
                    new_item = {
                        "id": iid,
                        "name": str(item.get("name", "Item")).strip() or "Item",
                        "category_id": cid,
                        "last_page_index": int(item.get("last_page_index", 0)),
                        "pages": item.get("pages", []),
                    }
                    new_data["items"].append(new_item)
        
        # root 객체에서 시작
        root_obj = old_data.get("root", {})
        if root_obj:
            root_cats = root_obj.get("categories", [])
            if isinstance(root_cats, list):
                for root_cat in root_cats:
                    extract_categories(root_cat, parent_id=None)
        
        # root 객체의 items도 처리 (최상위 아이템)
        root_items = root_obj.get("items", []) if root_obj else []
        if isinstance(root_items, list) and root_items:
            # root 아이템들을 위한 임시 카테고리 생성
            temp_root_id = _uuid()
            new_data["root_category_ids"].append(temp_root_id)
            new_data["categories"].append({
                "id": temp_root_id,
                "name": "General",
                "parent_id": None,
                "child_ids": [],
                "item_ids": [],
            })
            for item in root_items:
                iid = str(item.get("id", _uuid()))
                new_data["categories"][-1]["item_ids"].append(iid)
                new_data["items"].append({
                    "id": iid,
                    "name": str(item.get("name", "Item")).strip() or "Item",
                    "category_id": temp_root_id,
                    "last_page_index": int(item.get("last_page_index", 0)),
                    "pages": item.get("pages", []),
                })
        
        return new_data

    def _ensure_integrity(self) -> None:
        # 카테고리가 없어도 허용 (사용자가 모든 폴더를 삭제할 수 있도록)
        # 초기 로드 시에만 _default_data()를 사용 (load() 함수에서 처리)
        # if not self.categories:
        #     base = self._default_data()
        #     self._parse_categories_items(base)
        #     self.root_category_ids = base["root_category_ids"]

        # root_category_ids 복구: parent_id가 None인 카테고리 찾기
        if not self.root_category_ids:
            self.root_category_ids = [cid for cid, c in self.categories.items() if not c.parent_id]
            # parent_id가 None인 카테고리가 없으면, 모든 카테고리 중 첫 번째를 root로 설정
            if not self.root_category_ids and self.categories:
                self.root_category_ids = [next(iter(self.categories.keys()))]
        
        # ROOT 폴더가 없으면 자동 생성
        if ROOT_CATEGORY_ID not in self.categories:
            self.categories[ROOT_CATEGORY_ID] = Category(
                id=ROOT_CATEGORY_ID,
                name="ROOT",
                parent_id=None,
                child_ids=[],
                item_ids=[],
                url=""
            )
            print(f"[DEBUG] ROOT 폴더 자동 생성")
        
        # root_category_ids 검증: 저장된 root_category_ids가 실제로 존재하는지 확인
        valid_root_ids = []
        for rid in self.root_category_ids:
            if rid in self.categories:
                c = self.categories[rid]
                # parent_id가 None이거나 parent가 존재하지 않으면 root로 인정
                if not c.parent_id or c.parent_id not in self.categories:
                    valid_root_ids.append(rid)
        
        # ROOT 폴더를 항상 첫 번째로 포함
        if ROOT_CATEGORY_ID not in valid_root_ids:
            valid_root_ids.insert(0, ROOT_CATEGORY_ID)
        
        # 유효한 root가 없으면 parent_id가 None인 카테고리를 찾아서 추가
        if not valid_root_ids:
            roots = [cid for cid, c in self.categories.items() if not c.parent_id]
            if roots:
                valid_root_ids = roots
            elif self.categories:
                # 모든 카테고리가 자식인 경우, 첫 번째 카테고리를 root로 설정
                valid_root_ids = [next(iter(self.categories.keys()))]
        
        # ROOT 폴더를 항상 첫 번째로 보장
        if ROOT_CATEGORY_ID in valid_root_ids:
            valid_root_ids.remove(ROOT_CATEGORY_ID)
            valid_root_ids.insert(0, ROOT_CATEGORY_ID)
        else:
            valid_root_ids.insert(0, ROOT_CATEGORY_ID)
        
        self.root_category_ids = valid_root_ids

        # ROOT 폴더는 항상 parent_id가 None이어야 함
        if ROOT_CATEGORY_ID in self.categories:
            self.categories[ROOT_CATEGORY_ID].parent_id = None
        
        for cid, c in self.categories.items():
            # ROOT 폴더는 다른 폴더의 자식이 될 수 없음
            if cid == ROOT_CATEGORY_ID:
                c.parent_id = None
            # ROOT 폴더를 자식으로 가질 수 없음
            if ROOT_CATEGORY_ID in c.child_ids:
                c.child_ids.remove(ROOT_CATEGORY_ID)
            
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

        # ROOT 폴더를 항상 첫 번째로 처리
        if ROOT_CATEGORY_ID in self.categories:
            dfs(ROOT_CATEGORY_ID)
        
        # 나머지 root 폴더들 처리
        for r in self.root_category_ids:
            if r != ROOT_CATEGORY_ID:
                dfs(r)
        
        # 아직 처리되지 않은 카테고리들 처리
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
        c = Category(id=cid, name=name, parent_id=parent_id, child_ids=[], item_ids=[], url="")
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
        
        # ROOT 폴더는 삭제 불가
        if cid == ROOT_CATEGORY_ID:
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
        
        # ROOT 폴더는 삭제 불가
        if cid == ROOT_CATEGORY_ID:
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

    def export_to_zip(self, zip_path: str) -> Tuple[bool, Optional[str]]:
        """
        전체 데이터를 ZIP 파일로 내보내기
        Returns: (success: bool, error_message: Optional[str])
        """
        try:
            # 1. 임시 디렉토리 생성
            import tempfile
            temp_dir = tempfile.mkdtemp()
            export_json_path = os.path.join(temp_dir, "notes_db.json")
            
            # 2. 현재 데이터를 JSON으로 저장
            self._ensure_integrity()
            self.data["version"] = "0.6.0"
            self.data["updated_at"] = _now_epoch()
            self.data["ui_state"] = self.ui_state.copy() if isinstance(self.ui_state, dict) else {}
            self.data["global_ideas"] = self.global_ideas.copy() if isinstance(self.global_ideas, list) else []
            self.data["root_category_ids"] = list(self.root_category_ids)
            
            try:
                self.data["categories"] = [self._serialize_category(self.categories[cid]) for cid in self._all_category_ids_in_stable_order()]
            except Exception as e:
                return False, f"Failed to serialize categories: {str(e)}"
            
            try:
                self.data["items"] = [self._serialize_item(self.items[iid]) for iid in self._all_item_ids_in_stable_order()]
            except Exception as e:
                return False, f"Failed to serialize items: {str(e)}"
            
            # JSON 파일 저장
            with open(export_json_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            
            # 3. 참조되는 모든 이미지 파일 수집
            image_files = set()
            for item in self.items.values():
                for page in item.pages:
                    if page.image_a_path:
                        abs_path = _abspath_from_rel(page.image_a_path)
                        if os.path.exists(abs_path):
                            image_files.add((abs_path, page.image_a_path))
                    if page.image_b_path:
                        abs_path = _abspath_from_rel(page.image_b_path)
                        if os.path.exists(abs_path):
                            image_files.add((abs_path, page.image_b_path))
            
            # 4. ZIP 파일 생성
            _ensure_dir(os.path.dirname(zip_path) or ".")
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # JSON 파일 추가
                zipf.write(export_json_path, "notes_db.json")
                
                # 이미지 파일들 추가 (디렉토리 구조 유지)
                for abs_path, rel_path in image_files:
                    if os.path.exists(abs_path):
                        zipf.write(abs_path, rel_path)
            
            # 5. 임시 디렉토리 정리
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            
            return True, None
            
        except Exception as e:
            return False, f"Export failed: {str(e)}"

    def import_from_zip(self, zip_path: str, merge_mode: bool = False) -> Tuple[bool, Optional[str]]:
        """
        ZIP 파일에서 데이터 가져오기
        Args:
            zip_path: ZIP 파일 경로
            merge_mode: True면 병합, False면 덮어쓰기
        Returns: (success: bool, error_message: Optional[str])
        """
        try:
            import tempfile
            temp_dir = tempfile.mkdtemp()
            
            # 1. ZIP 파일 압축 해제
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            # 2. JSON 파일 로드
            json_path = os.path.join(temp_dir, "notes_db.json")
            if not os.path.exists(json_path):
                shutil.rmtree(temp_dir)
                return False, "notes_db.json not found in ZIP file"
            
            with open(json_path, "r", encoding="utf-8") as f:
                imported_data = json.load(f)
            
            if not isinstance(imported_data, dict):
                shutil.rmtree(temp_dir)
                return False, "Invalid JSON format"
            
            # 3. 이미지 파일들을 assets 폴더로 복사
            assets_temp = os.path.join(temp_dir, ASSETS_DIR)
            if os.path.exists(assets_temp):
                for root, dirs, files in os.walk(assets_temp):
                    for file in files:
                        src_path = os.path.join(root, file)
                        rel_path = os.path.relpath(src_path, temp_dir)
                        dst_path = _abspath_from_rel(rel_path)
                        _ensure_dir(os.path.dirname(dst_path) or ".")
                        try:
                            shutil.copy2(src_path, dst_path)
                        except Exception:
                            pass  # 이미 존재하는 파일은 무시
            
            # 4. 데이터 병합 또는 덮어쓰기
            if merge_mode:
                # 병합 모드: 기존 데이터에 추가 (ID 충돌 시 새 ID 생성)
                self._merge_imported_data(imported_data)
            else:
                # 덮어쓰기 모드: 기존 데이터 완전 교체
                self.data = imported_data
                self._parse_categories_items(self.data)
            
            # 5. 무결성 검증
            self._ensure_integrity()
            
            # 6. 임시 디렉토리 정리
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            
            return True, None
            
        except zipfile.BadZipFile:
            return False, "Invalid ZIP file format"
        except Exception as e:
            return False, f"Import failed: {str(e)}"

    def _merge_imported_data(self, imported_data: Dict[str, Any]) -> None:
        """병합 모드: Import된 데이터를 기존 데이터에 병합"""
        # ID 매핑 (기존 ID -> 새 ID)
        category_id_map: Dict[str, str] = {}
        item_id_map: Dict[str, str] = {}
        
        # 카테고리 병합
        imported_categories = imported_data.get("categories", [])
        for cat_data in imported_categories:
            old_id = cat_data.get("id", "")
            if not old_id:
                continue
            
            # 기존에 같은 ID가 있으면 새 ID 생성
            if old_id in self.categories:
                new_id = _uuid()
                category_id_map[old_id] = new_id
                cat_data["id"] = new_id
            else:
                category_id_map[old_id] = old_id
            
            # parent_id 업데이트
            parent_id = cat_data.get("parent_id")
            if parent_id and parent_id in category_id_map:
                cat_data["parent_id"] = category_id_map[parent_id]
            elif parent_id and parent_id not in category_id_map:
                # 부모가 import되지 않은 경우 None으로 설정
                cat_data["parent_id"] = None
            
            # child_ids 업데이트
            child_ids = cat_data.get("child_ids", [])
            cat_data["child_ids"] = [category_id_map.get(cid, cid) for cid in child_ids if cid in category_id_map]
        
        # 아이템 병합
        imported_items = imported_data.get("items", [])
        for item_data in imported_items:
            old_id = item_data.get("id", "")
            if not old_id:
                continue
            
            # 기존에 같은 ID가 있으면 새 ID 생성
            if old_id in self.items:
                new_id = _uuid()
                item_id_map[old_id] = new_id
                item_data["id"] = new_id
            else:
                item_id_map[old_id] = old_id
            
            # category_id 업데이트
            cat_id = item_data.get("category_id", "")
            if cat_id and cat_id in category_id_map:
                item_data["category_id"] = category_id_map[cat_id]
            elif cat_id:
                # 카테고리가 import되지 않은 경우 root로 설정
                root_id = self.root_category_ids[0] if self.root_category_ids else None
                if root_id:
                    item_data["category_id"] = root_id
                else:
                    continue  # root가 없으면 스킵
            
            # 페이지 내 이미지 경로는 그대로 유지 (이미 복사됨)
        
        # 병합된 데이터를 기존 데이터에 추가
        existing_categories = [self._serialize_category(c) for c in self.categories.values()]
        existing_items = [self._serialize_item(i) for i in self.items.values()]
        
        # 카테고리 병합
        for cat_data in imported_categories:
            existing_categories.append(cat_data)
        
        # 아이템 병합
        for item_data in imported_items:
            existing_items.append(item_data)
        
        # root_category_ids 업데이트
        imported_root_ids = imported_data.get("root_category_ids", [])
        for root_id in imported_root_ids:
            mapped_id = category_id_map.get(root_id)
            if mapped_id and mapped_id not in self.root_category_ids:
                self.root_category_ids.append(mapped_id)
        
        # 데이터 업데이트
        self.data["categories"] = existing_categories
        self.data["items"] = existing_items
        
        # 파싱하여 메모리 구조 업데이트
        self._parse_categories_items(self.data)


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
# Custom Tree Widget for expand/collapse on icon click
# ---------------------------
class ExpandableTreeWidget(QTreeWidget):
    """아이콘 영역 클릭 시 확장/축소가 가능한 커스텀 트리 위젯"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon_click_pos = None  # 아이콘 클릭 위치 저장
    
    def _is_icon_area_click(self, pos):
        """클릭 위치가 아이콘 영역인지 확인"""
        icon_area_width = 20
        return pos.x() < icon_area_width
    
    def mousePressEvent(self, event):
        """마우스 클릭 시 아이콘 영역 클릭을 감지하여 확장/축소 처리"""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item and item.childCount() > 0:
                # 아이콘 영역 클릭: 확장/축소만 수행
                if self._is_icon_area_click(event.pos()):
                    self._icon_click_pos = event.pos()
                    item.setExpanded(not item.isExpanded())
                    return  # 선택 변경 없이 확장/축소만 수행
        
        self._icon_click_pos = None
        # 기본 동작 수행 (선택 등)
        super().mousePressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """더블 클릭 시 아이콘 영역 클릭을 감지하여 확장/축소 처리"""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item and item.childCount() > 0:
                # 아이콘 영역 클릭: 확장/축소만 수행
                if self._is_icon_area_click(event.pos()):
                    item.setExpanded(not item.isExpanded())
                    return  # 선택 변경 없이 확장/축소만 수행
        
        # 기본 동작 수행 (선택 등)
        super().mouseDoubleClickEvent(event)


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
        # 로드 후 데이터 상태 확인
        self.trace(f"데이터 로드 완료 - categories: {len(self.db.categories)}, items: {len(self.db.items)}, root_category_ids: {len(self.db.root_category_ids)}", "DEBUG")
        if not self.db.root_category_ids:
            self.trace("경고: root_category_ids가 비어있습니다!", "WARN")
        if len(self.db.categories) > 0 and len(self.db.root_category_ids) == 0:
            self.trace("경고: 카테고리는 있지만 root_category_ids가 비어있습니다! _ensure_integrity가 실행되었는지 확인 필요", "WARN")

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
        self._update_recent_items_list()  # 최근 작업 리스트 초기화

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
            # 트리 확장 상태 저장
            self._save_tree_expanded_state()
            # UI 상태 저장 및 DB 저장
            self._save_ui_state()
            self._save_db_with_warning()
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
        # 메뉴바 생성
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        
        # Export 메뉴
        export_action = file_menu.addAction("Export Data...")
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self.export_data)
        
        # Import 메뉴
        import_action = file_menu.addAction("Import Data...")
        import_action.setShortcut(QKeySequence("Ctrl+I"))
        import_action.triggered.connect(self.import_data)
        
        file_menu.addSeparator()
        
        # Save 메뉴 (기존 force_save와 연결)
        save_action = file_menu.addAction("Save")
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.force_save)
        
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

        self.nav_tree = ExpandableTreeWidget()
        self.nav_tree.setHeaderHidden(True)
        self.nav_tree.setUniformRowHeights(True)
        self.nav_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.nav_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.nav_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.nav_tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        
        # 트리 아이템 확장/축소 시 아이콘 업데이트
        self.nav_tree.itemExpanded.connect(self._on_tree_item_expanded)
        self.nav_tree.itemCollapsed.connect(self._on_tree_item_collapsed)
        
        # 더블 클릭 이벤트 처리 (단일 클릭과 동일하게 처리, 예외 방지)
        self.nav_tree.itemDoubleClicked.connect(self._on_tree_item_double_clicked)
        
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
        
        # 최근 작업 섹션
        recent_label = QLabel("최근 작업")
        recent_label.setStyleSheet("font-weight: 700; color: #666; padding: 4px 0px;")
        left_layout.addWidget(recent_label)
        
        self.recent_items_list = QListWidget()
        self.recent_items_list.setMaximumHeight(200)
        self.recent_items_list.itemClicked.connect(self._on_recent_item_clicked)
        left_layout.addWidget(self.recent_items_list)

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
        meta_layout = QHBoxLayout(meta_widget)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(6)
        
        # 좌측: Name, Ticker 영역 (모두 같은 줄에 표시)
        left_meta = QWidget()
        left_meta_layout = QHBoxLayout(left_meta)
        left_meta_layout.setContentsMargins(0, 0, 0, 0)
        left_meta_layout.setSpacing(6)
        
        lbl_name = QLabel("Name:")
        lbl_name.setFixedHeight(26)
        lbl_name.setAlignment(Qt.AlignVCenter)
        left_meta_layout.addWidget(lbl_name)
        
        self.edit_stock_name = QLineEdit()
        self.edit_stock_name.setFixedSize(220, 26)
        self.edit_stock_name.textChanged.connect(self._on_page_field_changed)
        left_meta_layout.addWidget(self.edit_stock_name)
        
        lbl_ticker = QLabel("Ticker:")
        lbl_ticker.setFixedHeight(26)
        lbl_ticker.setAlignment(Qt.AlignVCenter)
        left_meta_layout.addWidget(lbl_ticker)
        
        self.edit_ticker = QLineEdit()
        self.edit_ticker.setFixedSize(120, 26)
        self.edit_ticker.textChanged.connect(self._on_page_field_changed)
        left_meta_layout.addWidget(self.edit_ticker)
        
        self.btn_copy_ticker = QToolButton()
        self.btn_copy_ticker.setIcon(_make_copy_icon(16))
        self.btn_copy_ticker.setToolTip("Copy ticker to clipboard")
        self.btn_copy_ticker.setFixedSize(30, 26)
        self.btn_copy_ticker.clicked.connect(self.copy_ticker)
        left_meta_layout.addWidget(self.btn_copy_ticker)
        
        meta_layout.addWidget(left_meta, 0)  # stretch factor 0으로 설정하여 필요한 만큼만 차지
        meta_layout.addStretch()  # 좌측과 우측 사이 공간
        
        # 우측: Description 토글 버튼 (Chart 너비에 맞춰 우측 정렬)
        self.btn_toggle_desc = QToolButton()
        self.btn_toggle_desc.setCheckable(True)
        self.btn_toggle_desc.setChecked(self._desc_visible)
        self.btn_toggle_desc.setToolTip("Show/Hide Description panel")
        self.btn_toggle_desc.setFixedSize(100, 26)
        self.btn_toggle_desc.toggled.connect(self._on_toggle_desc)
        self._update_desc_toggle_button_text()
        meta_layout.addWidget(self.btn_toggle_desc)
        
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
        self.btn_prev = QToolButton(); self.btn_prev.setText("◀"); self.btn_prev.setFixedSize(32, 26); self.btn_prev.setToolTip("Previous Page"); self.btn_prev.clicked.connect(self.go_prev_page)
        self.lbl_page = QLabel("0 / 0"); self.lbl_page.setAlignment(Qt.AlignCenter); self.lbl_page.setMinimumWidth(80)
        self.btn_next = QToolButton(); self.btn_next.setText("▶"); self.btn_next.setFixedSize(32, 26); self.btn_next.setToolTip("Next Page"); self.btn_next.clicked.connect(self.go_next_page)
        self.btn_add_page = QToolButton(); self.btn_add_page.setText("+"); self.btn_add_page.setFixedSize(32, 26); self.btn_add_page.setToolTip("Add Page"); self.btn_add_page.clicked.connect(self.add_page)
        self.btn_del_page = QToolButton(); self.btn_del_page.setText("×"); self.btn_del_page.setFixedSize(32, 26); self.btn_del_page.setToolTip("Delete Page"); self.btn_del_page.clicked.connect(self.delete_page)
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

        # 리스트 버튼들 (checkable로 변경하여 상태 표시)
        self.btn_bullets = QToolButton(); self.btn_bullets.setText("•"); self.btn_bullets.setFixedSize(28, 26); self.btn_bullets.setToolTip("Bulleted List"); self.btn_bullets.setCheckable(True)
        self.btn_numbered = QToolButton(); self.btn_numbered.setText("1."); self.btn_numbered.setFixedSize(32, 26); self.btn_numbered.setToolTip("Numbered List"); self.btn_numbered.setCheckable(True)
        self.btn_bullets.clicked.connect(lambda checked: self._toggle_list("bullet"))
        self.btn_numbered.clicked.connect(lambda checked: self._toggle_list("number"))
        
        # 리스트 제거 버튼
        self.btn_list_remove = QToolButton(); self.btn_list_remove.setText("×"); self.btn_list_remove.setFixedSize(28, 26); self.btn_list_remove.setToolTip("Remove List")
        self.btn_list_remove.clicked.connect(self._remove_list)
        
        # 리스트 들여쓰기/내어쓰기 버튼
        self.btn_list_indent = QToolButton(); self.btn_list_indent.setText("→"); self.btn_list_indent.setFixedSize(28, 26); self.btn_list_indent.setToolTip("Indent List (Tab)")
        self.btn_list_outdent = QToolButton(); self.btn_list_outdent.setText("←"); self.btn_list_outdent.setFixedSize(28, 26); self.btn_list_outdent.setToolTip("Outdent List (Shift+Tab)")
        self.btn_list_indent.clicked.connect(self._indent_list)
        self.btn_list_outdent.clicked.connect(self._outdent_list)

        self.btn_ideas = QToolButton(); self.btn_ideas.setText("💡 Ideas"); self.btn_ideas.setCheckable(True)
        self.btn_ideas.setFixedSize(100, 32)  # 더 크고 부각되도록
        self.btn_ideas.setToolTip("Toggle Global Ideas panel (전역 아이디어)")
        self.btn_ideas.setStyleSheet("""
            QToolButton {
                font-weight: 600;
                font-size: 10pt;
                background: #F0F0F0;
                border: 2px solid #CCCCCC;
                border-radius: 6px;
            }
            QToolButton:hover {
                background: #E8E8E8;
                border: 2px solid #999999;
            }
            QToolButton:checked {
                background: #E3F2FD;
                border: 2px solid #2196F3;
                color: #1976D2;
            }
            QToolButton:checked:hover {
                background: #BBDEFB;
            }
        """)
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
        r2.addWidget(self.btn_list_remove)
        r2.addWidget(_vsep())
        r2.addWidget(self.btn_list_outdent)
        r2.addWidget(self.btn_list_indent)
        r2.addStretch(1)

        fmt_outer.addWidget(row1)
        fmt_outer.addWidget(row2)

        self.notes_ideas_splitter = QSplitter(Qt.Horizontal)
        self.notes_ideas_splitter.setChildrenCollapsible(False)

        self.notes_left = QWidget()
        notes_left_l = QVBoxLayout(self.notes_left)
        notes_left_l.setContentsMargins(0,0,0,0)
        notes_left_l.setSpacing(6)

        # Checklist 탭 위젯
        self.chk_tabs = QTabWidget()
        
        # 기본 Checklist 탭
        self.chk_default_tab = QWidget()
        chk_default_layout = QVBoxLayout(self.chk_default_tab)
        chk_default_layout.setContentsMargins(10,10,10,10)
        chk_default_layout.setSpacing(6)

        self.chk_boxes: List[QCheckBox] = []
        self.chk_notes: List[QTextEdit] = []
        for q in DEFAULT_CHECK_QUESTIONS:
            cb = QCheckBox(q)
            # 체크 상태에 따라 질문 텍스트 색상 변경
            cb.stateChanged.connect(self._on_page_field_changed)
            cb.stateChanged.connect(lambda state, checkbox=cb: self._update_checkbox_color(checkbox, state))
            # 초기 스타일 설정
            cb.setStyleSheet("""
                QCheckBox {
                    color: #222222;
                }
                QCheckBox:checked {
                    color: #2D6BFF;
                }
            """)
            self.chk_boxes.append(cb)
            note = QTextEdit()
            note.setPlaceholderText("간단 설명을 입력하세요... (서식/색상 가능)")
            note.setFixedHeight(54)
            note.textChanged.connect(self._on_page_field_changed)
            note.installEventFilter(self)
            note.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
            note.setTabChangesFocus(False)
            self.chk_notes.append(note)
            chk_default_layout.addWidget(cb)
            chk_default_layout.addWidget(note)
        chk_default_layout.addStretch()
        self.chk_tabs.addTab(self.chk_default_tab, "기본 Checklist")
        
        # Custom Checklist 탭
        self.chk_custom_tab = QWidget()
        chk_custom_layout = QVBoxLayout(self.chk_custom_tab)
        chk_custom_layout.setContentsMargins(10,10,10,10)
        chk_custom_layout.setSpacing(6)
        
        # Custom Checklist 컨테이너 (스크롤 가능)
        self.chk_custom_scroll = QScrollArea()
        self.chk_custom_scroll.setWidgetResizable(True)
        self.chk_custom_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chk_custom_scroll_widget = QWidget()
        self.chk_custom_scroll_layout = QVBoxLayout(self.chk_custom_scroll_widget)
        self.chk_custom_scroll_layout.setContentsMargins(0,0,0,0)
        self.chk_custom_scroll_layout.setSpacing(6)
        self.chk_custom_scroll.setWidget(self.chk_custom_scroll_widget)
        
        # Custom Checklist 항목 추가 버튼
        self.chk_custom_add_btn = QPushButton("+ 항목 추가")
        self.chk_custom_add_btn.clicked.connect(self._on_add_custom_checklist_item)
        chk_custom_layout.addWidget(self.chk_custom_add_btn)
        chk_custom_layout.addWidget(self.chk_custom_scroll)
        
        self.chk_tabs.addTab(self.chk_custom_tab, "Custom Checklist")
        
        # Custom Checklist UI 요소 저장
        self.chk_custom_items: List[Dict[str, Any]] = []  # [{"cb": QCheckBox, "q_edit": QLineEdit, "note": QTextEdit, "del_btn": QPushButton, "widget": QWidget}, ...]

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("추가 분석/설명을 자유롭게 작성하세요... (서식/색상 가능)")
        self.text_edit.textChanged.connect(self._on_page_field_changed)
        self.text_edit.installEventFilter(self)
        self.text_edit.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
        self.text_edit.setTabChangesFocus(False)

        notes_left_l.addWidget(self.chk_tabs)
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
        
        # Ideas 탭 위젯
        self.ideas_tabs = QTabWidget()
        self.ideas_tabs.setTabsClosable(False)  # X 버튼 제거
        self.ideas_tabs.currentChanged.connect(self._on_ideas_tab_changed)
        # 탭 더블 클릭 시 이름 변경
        self.ideas_tabs.tabBarDoubleClicked.connect(self._on_ideas_tab_double_clicked)
        
        # 탭 추가/삭제 버튼 (page 추가/삭제와 동일한 스타일)
        ideas_header = QWidget()
        ideas_header_l = QHBoxLayout(ideas_header)
        ideas_header_l.setContentsMargins(0, 0, 0, 0)
        ideas_header_l.setSpacing(6)
        self.lbl_ideas = QLabel("Global Ideas"); self.lbl_ideas.setStyleSheet("font-weight: 700;")
        ideas_header_l.addWidget(self.lbl_ideas)
        ideas_header_l.addStretch()
        self.btn_del_ideas_tab = QToolButton()
        self.btn_del_ideas_tab.setText("−")
        self.btn_del_ideas_tab.setFixedSize(32, 26)
        self.btn_del_ideas_tab.setToolTip("Delete Current Tab (현재 탭 삭제)")
        self.btn_del_ideas_tab.clicked.connect(self._on_delete_current_ideas_tab)
        self.btn_add_ideas_tab = QToolButton()
        self.btn_add_ideas_tab.setText("+")
        self.btn_add_ideas_tab.setFixedSize(32, 26)
        self.btn_add_ideas_tab.setToolTip("Add Ideas Tab (최대 10개)")
        self.btn_add_ideas_tab.clicked.connect(self._on_add_ideas_tab)
        ideas_header_l.addWidget(self.btn_del_ideas_tab)
        ideas_header_l.addWidget(self.btn_add_ideas_tab)
        
        ideas_l.addWidget(ideas_header)
        ideas_l.addWidget(self.ideas_tabs, 1)
        
        # Ideas 탭 데이터 저장
        self.ideas_tab_editors: List[QTextEdit] = []  # 각 탭의 QTextEdit 저장

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
        color_l.addWidget(QLabel("Color:"))
        
        # 색상 버튼 그룹 (라디오 버튼처럼 동작)
        color_group = QButtonGroup(color_row)
        color_buttons = {}
        
        def _mk_anno_color_btn(color_hex: str, tooltip: str) -> QToolButton:
            """Annotation 색상 버튼 생성"""
            btn = QToolButton(color_row)
            btn.setCheckable(True)
            btn.setFixedSize(32, 32)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(f"""
                QToolButton {{
                    background-color: {color_hex};
                    border: 2px solid #CCCCCC;
                    border-radius: 4px;
                }}
                QToolButton:checked {{
                    border: 3px solid #000000;
                }}
                QToolButton:hover {{
                    border: 3px solid #666666;
                }}
            """)
            return btn
        
        # 색상 버튼들 생성
        btn_color_red = _mk_anno_color_btn(COLOR_RED, "Red")
        btn_color_yellow = _mk_anno_color_btn(COLOR_YELLOW, "Yellow")
        btn_color_cyan = _mk_anno_color_btn("#00D5FF", "Cyan")
        btn_color_white = _mk_anno_color_btn("#FFFFFF", "White")
        
        # 기본 선택: Red
        btn_color_red.setChecked(True)
        
        # 버튼 그룹에 추가
        color_group.addButton(btn_color_red, 0)
        color_group.addButton(btn_color_yellow, 1)
        color_group.addButton(btn_color_cyan, 2)
        color_group.addButton(btn_color_white, 3)
        
        # 색상 매핑
        color_map = {
            0: COLOR_RED,
            1: COLOR_YELLOW,
            2: "#00D5FF",
            3: "#FFFFFF"
        }
        
        color_l.addWidget(btn_color_red)
        color_l.addWidget(btn_color_yellow)
        color_l.addWidget(btn_color_cyan)
        color_l.addWidget(btn_color_white)
        color_l.addStretch()
        
        p_layout.addWidget(color_row)
        
        # 색상 선택 함수
        def on_color_changed(btn_id: int):
            color_hex = color_map.get(btn_id, COLOR_RED)
            viewer.set_pen(color_hex, float(combo_width.currentData()))
        
        color_group.buttonClicked.connect(lambda btn: on_color_changed(color_group.id(btn)))

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
            # 현재 선택된 색상 버튼의 색상 가져오기
            checked_btn = color_group.checkedButton()
            if checked_btn:
                btn_id = color_group.id(checked_btn)
                color_hex = color_map.get(btn_id, COLOR_RED)
            else:
                color_hex = COLOR_RED  # 기본값
            viewer.set_pen(color_hex, float(combo_width.currentData()))

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
        self.trace(f"_refresh_nav_tree() 시작 - root_category_ids: {self.db.root_category_ids}, categories: {len(self.db.categories)}, items: {len(self.db.items)}", "DEBUG")
        # 저장된 확장 상태를 미리 가져옴 (clear 전에)
        expanded_categories = self.db.ui_state.get("tree_expanded_categories", [])
        if isinstance(expanded_categories, list):
            expanded_set = set(str(x) for x in expanded_categories if str(x))
        else:
            expanded_set = set()
        
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
            
            # URL이 있으면 폴더 이름에 링크 표시 추가
            display_name = c.name
            if c.url and c.url.strip():
                display_name = f"{c.name} 🔗"
            
            q = QTreeWidgetItem([display_name])
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
            
            # URL이 있으면 툴팁에 표시 및 색상 변경
            if c.url and c.url.strip():
                q.setToolTip(0, f"URL: {c.url}\n우클릭하여 열기")
                # URL이 있는 폴더는 파란색으로 표시
                q.setForeground(0, QColor("#0066CC"))
            
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

        self.trace(f"트리 구성 시작 - root_category_ids 개수: {len(self.db.root_category_ids)}", "DEBUG")
        # ROOT 폴더를 항상 첫 번째로 표시
        if ROOT_CATEGORY_ID in self.db.root_category_ids:
            self.trace(f"  ROOT 카테고리 추가: {ROOT_CATEGORY_ID}", "DEBUG")
            add_cat(ROOT_CATEGORY_ID, None)
        # 나머지 root 폴더들 추가
        for rid in self.db.root_category_ids:
            if rid != ROOT_CATEGORY_ID:
                self.trace(f"  root 카테고리 추가: {rid}", "DEBUG")
                add_cat(rid, None)
        self.trace(f"트리 구성 완료 - topLevelItemCount: {self.nav_tree.topLevelItemCount()}", "DEBUG")

        # 모든 카테고리의 아이콘 초기화 (모두 축소 상태로)
        for cid, qitem in cat_to_qitem.items():
            if qitem.childCount() > 0:
                qitem.setIcon(0, _make_expand_icon(16, expanded=False))
        
        # blockSignals 해제
        self.nav_tree.blockSignals(False)
        
        # 저장된 확장 상태 복원 (트리 구성 완료 후 즉시 복원)
        self.trace(f"트리 확장 상태 복원 시작 - 저장된 확장 카테고리: {expanded_set}, 리스트: {expanded_categories}", "DEBUG")
        self.trace(f"cat_to_qitem 키: {list(cat_to_qitem.keys())}", "DEBUG")
        
        if expanded_set:
            # 저장된 확장 상태 복원 - cat_to_qitem 맵을 직접 사용
            self.trace(f"저장된 확장 상태 복원 시작 - 확장할 카테고리: {expanded_set}", "DEBUG")
            # 저장된 순서대로 부모부터 확장 (부모가 확장되어야 자식이 보임)
            for cid in expanded_categories:
                cid_str = str(cid)
                if cid_str in expanded_set and cid_str in cat_to_qitem:
                    qitem = cat_to_qitem[cid_str]
                    if qitem.childCount() > 0:
                        qitem.setExpanded(True)
                        qitem.setIcon(0, _make_expand_icon(16, expanded=True))
                        self.trace(f"카테고리 확장 성공: {cid_str}", "DEBUG")
                    else:
                        self.trace(f"카테고리 확장 실패 (자식 없음): {cid_str}", "DEBUG")
                elif cid_str in expanded_set:
                    self.trace(f"카테고리 확장 실패 (cat_to_qitem에 없음): {cid_str}", "DEBUG")
            
            # 모든 카테고리의 아이콘 최종 업데이트
            for cid, qitem in cat_to_qitem.items():
                if qitem.childCount() > 0:
                    qitem.setIcon(0, _make_expand_icon(16, expanded=qitem.isExpanded()))
        else:
            self.trace("저장된 확장 상태 없음 - 모두 축소 상태 유지", "DEBUG")

        if select_current:
            if self.current_item_id and self.current_item_id in item_to_qitem:
                self.nav_tree.setCurrentItem(item_to_qitem[self.current_item_id])
            elif self.current_category_id and self.current_category_id in cat_to_qitem:
                self.nav_tree.setCurrentItem(cat_to_qitem[self.current_category_id])

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
            cid = str(item.data(0, self.CATEGORY_ID_ROLE) or "")
            cat = self.db.get_category(cid) if cid else None
            has_url = cat and cat.url and cat.url.strip()
            
            act_add_folder = menu.addAction("+ Folder (sub)")
            act_add_item = menu.addAction("+ Item")
            menu.addSeparator()
            act_rename = menu.addAction("Rename Folder")
            act_delete = menu.addAction("Delete Folder")
            menu.addSeparator()
            act_up = menu.addAction("Move Folder Up")
            act_down = menu.addAction("Move Folder Down")
            menu.addSeparator()
            # URL 관련 메뉴
            if has_url:
                act_open_url = menu.addAction("Open URL")
                act_edit_url = menu.addAction("Edit URL...")
                act_remove_url = menu.addAction("Remove URL")
            else:
                act_set_url = menu.addAction("Set URL...")
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
            elif has_url and chosen == act_open_url:
                self._open_folder_url(cid)
            elif has_url and chosen == act_edit_url:
                self._edit_folder_url(cid)
            elif has_url and chosen == act_remove_url:
                self._remove_folder_url(cid)
            elif not has_url and chosen == act_set_url:
                self._set_folder_url(cid)
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
        # 트리 확장 상태 저장
        self._save_tree_expanded_state()
    
    def _save_tree_expanded_state(self) -> None:
        """현재 트리의 확장된 카테고리 ID 목록을 저장"""
        expanded_ids = []
        
        def collect_expanded(item: QTreeWidgetItem):
            node_type = item.data(0, self.NODE_TYPE_ROLE)
            if node_type == "category" and item.isExpanded() and item.childCount() > 0:
                cid = str(item.data(0, self.CATEGORY_ID_ROLE) or "")
                if cid:
                    expanded_ids.append(cid)
            for i in range(item.childCount()):
                collect_expanded(item.child(i))
        
        for i in range(self.nav_tree.topLevelItemCount()):
            collect_expanded(self.nav_tree.topLevelItem(i))
        
        self.db.ui_state["tree_expanded_categories"] = expanded_ids
        print(f"[DEBUG] 트리 확장 상태 저장: {expanded_ids}")

    # ---------------- Tree expand/collapse icon update ----------------
    def _on_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        """트리 아이템 확장 시 아이콘을 - 모양으로 변경"""
        if item.childCount() > 0:
            item.setIcon(0, _make_expand_icon(16, expanded=True))
        # 확장 상태 저장 (debounce를 위해 타이머 사용)
        if not hasattr(self, '_tree_state_save_timer'):
            self._tree_state_save_timer = QTimer(self)
            self._tree_state_save_timer.setSingleShot(True)
            def save_and_persist():
                self._save_tree_expanded_state()
                self._save_ui_state()
                self._save_db_with_warning()
            self._tree_state_save_timer.timeout.connect(save_and_persist)
        self._tree_state_save_timer.stop()
        self._tree_state_save_timer.start(500)  # 500ms 후 저장
    
    def _on_tree_item_collapsed(self, item: QTreeWidgetItem) -> None:
        """트리 아이템 축소 시 아이콘을 + 모양으로 변경"""
        if item.childCount() > 0:
            item.setIcon(0, _make_expand_icon(16, expanded=False))
        # 축소 상태 저장 (debounce를 위해 타이머 사용)
        if not hasattr(self, '_tree_state_save_timer'):
            self._tree_state_save_timer = QTimer(self)
            self._tree_state_save_timer.setSingleShot(True)
            def save_and_persist():
                self._save_tree_expanded_state()
                self._save_ui_state()
                self._save_db_with_warning()
            self._tree_state_save_timer.timeout.connect(save_and_persist)
        self._tree_state_save_timer.stop()
        self._tree_state_save_timer.start(500)  # 500ms 후 저장
    
    # ---------------- Selection changed ---------------- 
    def _on_tree_selection_changed(self) -> None:
        try:
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
                # pages가 비어있지 않은지 확인
                if not it.pages:
                    self.trace(f"경고: 아이템 '{it.name}'에 페이지가 없습니다. 기본 페이지를 생성합니다.", "WARN")
                    it.pages = [self.db.new_page()]
                self.current_page_index = max(0, min(it.last_page_index, len(it.pages) - 1))
                
                # 마지막 접근 시간 업데이트
                it.last_accessed_at = _now_epoch()
                self._update_recent_items_list()
                
                self._save_ui_state()

                self._show_placeholder(False)
                self._load_current_item_page_to_ui()
                self.trace(f"Selected item: {it.name}", "INFO")
                return
        except Exception as e:
            self.trace(f"트리 선택 변경 중 오류 발생: {str(e)}", "ERROR")
            import traceback
            self.trace(traceback.format_exc(), "ERROR")
    
    def _on_tree_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """트리 아이템 더블 클릭 처리 (아이콘 영역이 아닌 경우에만 선택 처리)"""
        try:
            # ExpandableTreeWidget에서 아이콘 영역 클릭은 이미 처리됨
            # 여기서는 아이콘 영역이 아닌 경우에만 선택 처리
            node_type = item.data(0, self.NODE_TYPE_ROLE)
            if node_type == "item":
                # 아이템은 선택 변경 이벤트를 트리거 (단일 클릭과 동일)
                self.nav_tree.setCurrentItem(item)
        except Exception as e:
            self.trace(f"트리 더블 클릭 처리 중 오류 발생: {str(e)}", "ERROR")
            import traceback
            self.trace(traceback.format_exc(), "ERROR")

    # ---------------- Safe save wrapper ----------------
    def _save_db_with_warning(self) -> bool:
        self.trace("_save_db_with_warning() 호출됨", "DEBUG")
        ok, error_msg = self.db.save()
        if ok:
            self.trace("저장 성공", "DEBUG")
            return True
        self.trace(f"저장 실패: {error_msg}", "DEBUG")
        
        # 저장 실패 시 상세한 에러 로그 및 경고
        now = time.time()
        if (now - self._last_save_warn_ts) >= self._save_warn_cooldown_sec:
            self._last_save_warn_ts = now
            
            # 상세한 에러 로그
            error_detail = error_msg or "Unknown error"
            self.trace(f"Save failed: {error_detail}", "WARN")
            
            # 사용자에게 상세한 경고 메시지 표시
            warning_msg = "JSON 저장에 실패했습니다.\n\n"
            warning_msg += f"오류: {error_detail}\n\n"
            warning_msg += "조치:\n"
            warning_msg += "- VS Code에서 data/notes_db.json 탭을 닫거나 JSON Viewer/Preview 확장이 파일을 잡고 있지 않은지 확인\n"
            warning_msg += "- 앱이 2개 실행 중인지 확인\n"
            warning_msg += "- OneDrive/백신 실시간 감시가 잠깐 락을 거는 경우 잠시 후 자동 저장 재시도\n"
            warning_msg += "- 데이터 크기가 너무 큰 경우 일부 데이터를 정리하세요\n\n"
            warning_msg += "데이터 보호:\n"
            warning_msg += "- data/backups 폴더에 백업 파일이 생성되었을 수 있습니다\n"
            warning_msg += "- data 폴더에 notes_db.json.autosave.<timestamp>.json 파일이 생성되었을 수 있습니다"
            
            QMessageBox.warning(self, "Save warning", warning_msg)
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
                self._clear_custom_checklist_ui()
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
                checked = bool(cl[i].get("checked", False))
                self.chk_boxes[i].setChecked(checked)
                # 체크 상태에 따라 색상 업데이트
                self._update_checkbox_color(self.chk_boxes[i], Qt.Checked if checked else Qt.Unchecked)
                val = _strip_highlight_html(str(cl[i].get("note", "") or ""))
                self.chk_notes[i].setHtml(val) if _looks_like_html(val) else self.chk_notes[i].setPlainText(val)
            
            # Custom Checklist 로드
            custom_cl = _normalize_custom_checklist(pg.custom_checklist)
            self._load_custom_checklist_to_ui(custom_cl)

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
    
    def _collect_custom_checklist_from_ui(self) -> CustomChecklist:
        """Custom Checklist UI에서 데이터 수집"""
        out: CustomChecklist = []
        for item in self.chk_custom_items:
            q_text = item["q_edit"].text().strip()
            if q_text:  # 질문 텍스트가 있는 경우만 추가
                out.append({
                    "q": q_text,
                    "checked": bool(item["cb"].isChecked()),
                    "note": _strip_highlight_html(item["note"].toHtml())
                })
        return out
    
    def _on_add_custom_checklist_item(self) -> None:
        """Custom Checklist 항목 추가"""
        self._add_custom_checklist_item_ui("새 항목", False, "")
    
    def _add_custom_checklist_item_ui(self, question: str, checked: bool, note: str) -> None:
        """Custom Checklist 항목 UI 추가"""
        item_widget = QWidget()
        item_layout = QVBoxLayout(item_widget)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(4)
        
        # 상단: 체크박스 + 질문 입력 + 삭제 버튼
        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)
        
        cb = QCheckBox()
        cb.setChecked(checked)
        cb.stateChanged.connect(self._on_page_field_changed)
        cb.stateChanged.connect(lambda state, checkbox=cb: self._update_checkbox_color(checkbox, state))
        cb.setStyleSheet("""
            QCheckBox {
                color: #222222;
            }
            QCheckBox:checked {
                color: #2D6BFF;
            }
        """)
        
        q_edit = QLineEdit(question)
        q_edit.setPlaceholderText("질문을 입력하세요...")
        q_edit.textChanged.connect(self._on_page_field_changed)
        
        del_btn = QPushButton("삭제")
        del_btn.setFixedSize(50, 26)
        del_btn.clicked.connect(lambda: self._on_delete_custom_checklist_item(item_widget))
        
        top_layout.addWidget(cb)
        top_layout.addWidget(q_edit, 1)
        top_layout.addWidget(del_btn)
        
        # 하단: 설명 입력
        note_edit = QTextEdit()
        note_edit.setPlaceholderText("간단 설명을 입력하세요... (서식/색상 가능)")
        note_edit.setFixedHeight(54)
        if note:
            note_edit.setHtml(note) if _looks_like_html(note) else note_edit.setPlainText(note)
        note_edit.textChanged.connect(self._on_page_field_changed)
        note_edit.installEventFilter(self)
        note_edit.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
        note_edit.setTabChangesFocus(False)
        
        item_layout.addWidget(top_row)
        item_layout.addWidget(note_edit)
        
        # 저장
        item_data = {
            "widget": item_widget,
            "cb": cb,
            "q_edit": q_edit,
            "note": note_edit,
            "del_btn": del_btn
        }
        self.chk_custom_items.append(item_data)
        
        # 레이아웃에 추가
        self.chk_custom_scroll_layout.addWidget(item_widget)
        
        # 색상 업데이트
        self._update_checkbox_color(cb, Qt.Checked if checked else Qt.Unchecked)
    
    def _on_delete_custom_checklist_item(self, item_widget: QWidget) -> None:
        """Custom Checklist 항목 삭제"""
        # UI에서 제거
        for i, item in enumerate(self.chk_custom_items):
            if item["widget"] == item_widget:
                self.chk_custom_items.pop(i)
                item_widget.setParent(None)
                item_widget.deleteLater()
                self._on_page_field_changed()
                break
    
    def _clear_custom_checklist_ui(self) -> None:
        """Custom Checklist UI 초기화"""
        for item in self.chk_custom_items:
            item["widget"].setParent(None)
            item["widget"].deleteLater()
        self.chk_custom_items.clear()
    
    def _load_custom_checklist_to_ui(self, custom_checklist: CustomChecklist) -> None:
        """Custom Checklist 데이터를 UI에 로드"""
        self._clear_custom_checklist_ui()
        for item in custom_checklist:
            q_text = str(item.get("q", "")).strip()
            if q_text:  # 질문이 있는 경우만 추가
                checked = bool(item.get("checked", False))
                note = str(item.get("note", "") or "")
                self._add_custom_checklist_item_ui(q_text, checked, note)

    def _flush_page_fields_to_model_and_save(self) -> None:
        it = self.current_item()
        pg = self.current_page()
        if not it or not pg or self._loading_ui:
            try:
                new_global_ideas = self._collect_ideas_tabs_from_ui()
                if self.db.global_ideas != new_global_ideas:
                    # Global Ideas 변경 시 백업 생성
                    _backup_global_ideas(self.db.global_ideas)
                    self.db.global_ideas = new_global_ideas
                    self._save_ui_state()
                    self._save_db_with_warning()
            except Exception:
                pass
            return

        changed = False
        # Ideas 탭들 수집
        new_global_ideas = self._collect_ideas_tabs_from_ui()
        if self.db.global_ideas != new_global_ideas:
            # Global Ideas 변경 시 백업 생성
            _backup_global_ideas(self.db.global_ideas)
            self.db.global_ideas = new_global_ideas
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
        
        new_custom_checklist = self._collect_custom_checklist_from_ui()
        if pg.custom_checklist != new_custom_checklist:
            pg.custom_checklist = new_custom_checklist; changed = True

        it.last_page_index = self.current_page_index
        self._save_ui_state()

        if changed:
            pg.updated_at = _now_epoch()

        self._save_db_with_warning()

    def force_save(self) -> None:
        self._flush_page_fields_to_model_and_save()
        # 저장 성공 여부 확인
        save_ok = self._save_db_with_warning()
        if save_ok:
            QMessageBox.information(self, "저장 완료", "데이터가 성공적으로 저장되었습니다.")
        # 저장 실패 시 _save_db_with_warning에서 이미 경고 메시지를 표시함

    def _update_nav(self) -> None:
        it = self.current_item()
        total = len(it.pages) if it else 0
        cur = (self.current_page_index + 1) if total > 0 else 0
        self.lbl_page.setText(f"{cur} / {total}")
        self.btn_prev.setEnabled(total > 0 and self.current_page_index > 0)
        self.btn_next.setEnabled(total > 0 and self.current_page_index < total - 1)
        self.btn_del_page.setEnabled(total > 1)

    def _load_global_ideas_to_ui(self) -> None:
        """Ideas 탭들을 UI에 로드"""
        self._loading_ui = True
        try:
            # 기존 탭들 모두 제거
            self._clear_ideas_tabs()
            
            # 데이터에서 탭들 로드
            if not self.db.global_ideas:
                # 탭이 없으면 기본 탭 하나 생성
                self._add_ideas_tab_ui("Ideas 1", "")
            else:
                for idea in self.db.global_ideas:
                    name = str(idea.get("name", "")).strip() or "Ideas"
                    content = str(idea.get("content", "") or "")
                    self._add_ideas_tab_ui(name, content)
        finally:
            self._loading_ui = False
    
    def _add_ideas_tab_ui(self, name: str, content: str) -> None:
        """Ideas 탭 UI 추가"""
        if len(self.ideas_tab_editors) >= 10:
            QMessageBox.warning(self, "최대 개수", "Ideas 탭은 최대 10개까지 추가할 수 있습니다.")
            return
        
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        
        editor = QTextEdit()
        editor.setPlaceholderText("전역적으로 적용할 아이디어를 여기에 작성하세요... (서식/색상 가능)")
        if content:
            editor.setHtml(content) if _looks_like_html(content) else editor.setPlainText(content)
        editor.textChanged.connect(self._on_page_field_changed)
        editor.installEventFilter(self)
        editor.cursorPositionChanged.connect(self._on_any_rich_cursor_changed)
        editor.setTabChangesFocus(False)
        
        tab_layout.addWidget(editor)
        self.ideas_tab_editors.append(editor)
        
        tab_index = self.ideas_tabs.addTab(tab_widget, name)
        self.ideas_tabs.setCurrentIndex(tab_index)
    
    def _on_add_ideas_tab(self) -> None:
        """Ideas 탭 추가"""
        if len(self.ideas_tab_editors) >= 10:
            QMessageBox.warning(self, "최대 개수", "Ideas 탭은 최대 10개까지 추가할 수 있습니다.")
            return
        
        tab_num = len(self.ideas_tab_editors) + 1
        name = f"Ideas {tab_num}"
        self._add_ideas_tab_ui(name, "")
    
    def _on_delete_current_ideas_tab(self) -> None:
        """현재 선택된 Ideas 탭 삭제"""
        current_index = self.ideas_tabs.currentIndex()
        if current_index < 0:
            return
        
        if len(self.ideas_tab_editors) <= 1:
            QMessageBox.warning(self, "최소 개수", "Ideas 탭은 최소 1개는 유지해야 합니다.")
            return
        
        if 0 <= current_index < len(self.ideas_tab_editors):
            # 탭 이름 가져오기
            tab_name = self.ideas_tabs.tabText(current_index)
            
            # 사용자 확인
            reply = QMessageBox.question(
                self,
                "탭 삭제 확인",
                f"'{tab_name}' 탭을 삭제하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.ideas_tab_editors.pop(current_index)
                self.ideas_tabs.removeTab(current_index)
                
                # 삭제 후 현재 탭이 유효한지 확인하고 활성 편집기 설정
                new_index = self.ideas_tabs.currentIndex()
                if 0 <= new_index < len(self.ideas_tab_editors):
                    self._set_active_rich_edit(self.ideas_tab_editors[new_index])
                
                self._on_page_field_changed()
    
    def _on_ideas_tab_changed(self, index: int) -> None:
        """Ideas 탭 변경 시"""
        if 0 <= index < len(self.ideas_tab_editors):
            self._set_active_rich_edit(self.ideas_tab_editors[index])
    
    def _on_ideas_tab_double_clicked(self, index: int) -> None:
        """Ideas 탭 더블 클릭 시 이름 변경"""
        if index < 0 or index >= self.ideas_tabs.count():
            return
        
        current_name = self.ideas_tabs.tabText(index)
        new_name, ok = QInputDialog.getText(
            self,
            "탭 이름 변경",
            "새 탭 이름:",
            text=current_name
        )
        
        if ok and new_name.strip():
            new_name = new_name.strip()
            # 탭 이름 업데이트
            self.ideas_tabs.setTabText(index, new_name)
            # 데이터 저장
            self._on_page_field_changed()
    
    def _clear_ideas_tabs(self) -> None:
        """Ideas 탭들 모두 제거"""
        while self.ideas_tabs.count() > 0:
            self.ideas_tabs.removeTab(0)
        self.ideas_tab_editors.clear()
    
    def _collect_ideas_tabs_from_ui(self) -> List[Dict[str, str]]:
        """Ideas 탭들에서 데이터 수집"""
        out: List[Dict[str, str]] = []
        for i in range(self.ideas_tabs.count()):
            name = self.ideas_tabs.tabText(i)
            if i < len(self.ideas_tab_editors):
                editor = self.ideas_tab_editors[i]
                content = _strip_highlight_html(editor.toHtml())
                out.append({"name": name, "content": content})
        return out
    
    def _update_recent_items_list(self) -> None:
        """최근 작업 리스트 업데이트"""
        self.recent_items_list.clear()
        
        # 모든 item을 수집하고 last_accessed_at으로 정렬
        items_with_time = []
        for item in self.db.items.values():
            if item.last_accessed_at > 0:
                items_with_time.append(item)
        
        # 최신 순으로 정렬 (최근 10개만)
        items_with_time.sort(key=lambda x: x.last_accessed_at, reverse=True)
        items_with_time = items_with_time[:10]
        
        # 리스트에 추가
        for item in items_with_time:
            found = self.db.find_item(item.id)
            if not found:
                continue
            it, cat = found
            
            # 카테고리 경로 생성
            cat_path = []
            current_cat = cat
            while current_cat:
                cat_path.insert(0, current_cat.name)
                if current_cat.parent_id:
                    current_cat = self.db.get_category(current_cat.parent_id)
                else:
                    break
            
            path_str = " > ".join(cat_path) if cat_path else "ROOT"
            time_str = _format_relative_time(item.last_accessed_at)
            
            list_item = QListWidgetItem(f"{it.name}\n{path_str} • {time_str}")
            list_item.setData(Qt.UserRole, item.id)  # item ID 저장
            self.recent_items_list.addItem(list_item)
    
    def _on_recent_item_clicked(self, list_item: QListWidgetItem) -> None:
        """최근 작업 리스트에서 item 클릭 시 해당 item으로 이동"""
        item_id = list_item.data(Qt.UserRole)
        if not item_id:
            return
        
        # 트리에서 해당 item 찾기
        found = self.db.find_item(item_id)
        if not found:
            return
        
        it, cat = found
        
        # 트리에서 해당 item 찾아서 선택
        def find_item_in_tree(parent_item, target_id):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                node_type = child.data(0, self.NODE_TYPE_ROLE)
                if node_type == "item":
                    if str(child.data(0, self.ITEM_ID_ROLE) or "") == target_id:
                        return child
                elif node_type == "category":
                    result = find_item_in_tree(child, target_id)
                    if result:
                        return result
            return None
        
        # 트리에서 item 찾기
        for i in range(self.nav_tree.topLevelItemCount()):
            top_item = self.nav_tree.topLevelItem(i)
            found_item = find_item_in_tree(top_item, item_id)
            if found_item:
                # 부모 폴더들 확장
                parent = found_item.parent()
                while parent:
                    parent.setExpanded(True)
                    parent = parent.parent()
                
                # item 선택
                self.nav_tree.setCurrentItem(found_item)
                return

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
        # 아이템 ID만 사용하여 고유한 폴더명 생성 (UUID는 고유하므로 충돌 불가능)
        # UUID의 하이픈을 언더스코어로 변경하여 파일시스템 호환성 확보
        safe_item = it.id.replace("-", "_")
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
        # 아이템 ID만 사용하여 고유한 폴더명 생성 (UUID는 고유하므로 충돌 불가능)
        # UUID의 하이픈을 언더스코어로 변경하여 파일시스템 호환성 확보
        safe_item = it.id.replace("-", "_")
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

    # ---------------- Export / Import operations ----------------
    def export_data(self) -> None:
        """데이터를 ZIP 파일로 내보내기"""
        # 파일 저장 대화상자
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"notes_export_{timestamp}.zip"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Data",
            default_filename,
            "ZIP Files (*.zip);;All Files (*)"
        )
        if not file_path:
            return
        
        # Export 실행
        ok, error_msg = self.db.export_to_zip(file_path)
        if ok:
            QMessageBox.information(
                self,
                "Export Success",
                f"데이터가 성공적으로 내보내졌습니다.\n\n파일: {file_path}"
            )
        else:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"데이터 내보내기에 실패했습니다.\n\n오류: {error_msg or 'Unknown error'}"
            )

    def import_data(self) -> None:
        """ZIP 파일에서 데이터 가져오기"""
        # 파일 열기 대화상자
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Data",
            "",
            "ZIP Files (*.zip);;All Files (*)"
        )
        if not file_path:
            return
        
        # Import 모드 선택
        msg = QMessageBox(self)
        msg.setWindowTitle("Import Data")
        msg.setText("데이터 가져오기 방식을 선택하세요.")
        msg.setInformativeText(
            "병합: 기존 데이터에 추가 (ID 충돌 시 새 ID 생성)\n"
            "덮어쓰기: 기존 데이터를 완전히 교체"
        )
        btn_merge = msg.addButton("병합 (Merge)", QMessageBox.ActionRole)
        btn_replace = msg.addButton("덮어쓰기 (Replace)", QMessageBox.DestructiveRole)
        btn_cancel = msg.addButton("취소", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_cancel)
        msg.exec_()
        clicked = msg.clickedButton()
        
        if clicked == btn_cancel:
            return
        
        merge_mode = (clicked == btn_merge)
        
        # Import 전 백업 생성
        backup_path = _create_backup(self.db.db_path)
        if backup_path:
            self.trace(f"Backup created before import: {backup_path}", "INFO")
        
        # Import 실행
        ok, error_msg = self.db.import_from_zip(file_path, merge_mode=merge_mode)
        if ok:
            # UI 새로고침
            self._refresh_nav_tree(select_current=False)
            self._show_placeholder(True)
            self._load_current_item_page_to_ui(clear_only=True)
            self._load_global_ideas_to_ui()
            
            # 저장
            self._save_db_with_warning()
            
            mode_text = "병합" if merge_mode else "덮어쓰기"
            QMessageBox.information(
                self,
                "Import Success",
                f"데이터가 성공적으로 가져와졌습니다.\n\n모드: {mode_text}\n"
                f"파일: {file_path}"
            )
        else:
            QMessageBox.critical(
                self,
                "Import Failed",
                f"데이터 가져오기에 실패했습니다.\n\n오류: {error_msg or 'Unknown error'}\n\n"
                "백업 파일에서 복구할 수 있습니다."
            )

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
        self.trace(f"폴더 생성 시작 - 이름: {name.strip()}, parent_id: {parent_cid}", "DEBUG")
        c = self.db.add_category(name.strip(), parent_id=parent_cid if parent_cid else None)
        self.trace(f"폴더 생성 완료 - ID: {c.id}, root_category_ids: {self.db.root_category_ids}", "DEBUG")
        self.current_category_id = c.id
        self.current_item_id = ""
        self.current_page_index = 0
        self._save_ui_state()
        # 저장 성공 여부 확인
        self.trace("폴더 저장 시도...", "DEBUG")
        save_ok = self._save_db_with_warning()
        if not save_ok:
            # 저장 실패 시 폴더 롤백
            if c.id in self.db.categories:
                del self.db.categories[c.id]
            if c.id in self.db.root_category_ids:
                self.db.root_category_ids.remove(c.id)
            if parent_cid and parent_cid in self.db.categories:
                if c.id in self.db.categories[parent_cid].child_ids:
                    self.db.categories[parent_cid].child_ids.remove(c.id)
            QMessageBox.critical(
                self,
                "Save Failed",
                f"폴더 '{name.strip()}' 생성은 되었지만 저장에 실패했습니다.\n\n"
                "폴더가 저장되지 않았으므로 앱을 종료하면 사라집니다.\n\n"
                "다시 시도하거나 파일이 잠겨있는지 확인해주세요."
            )
            return
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
        
        # ROOT 폴더는 이름 변경 불가
        if cid == ROOT_CATEGORY_ID:
            QMessageBox.warning(self, "Cannot Rename", "ROOT 폴더의 이름은 변경할 수 없습니다.")
            return
        
        old_name = c.name
        new_name, ok = QInputDialog.getText(self, "Rename Folder", "New name:", text=c.name)
        if not ok or not (new_name or "").strip():
            return
        self.db.rename_category(cid, new_name.strip())
        save_ok = self._save_db_with_warning()
        if not save_ok:
            # 저장 실패 시 이름 롤백
            self.db.rename_category(cid, old_name)
            QMessageBox.critical(
                self,
                "Save Failed",
                f"폴더 이름 변경 저장에 실패했습니다.\n\n"
                "변경사항이 저장되지 않았으므로 앱을 종료하면 원래 이름으로 돌아갑니다."
            )
            return
        self._refresh_nav_tree(select_current=True)

    def delete_folder(self) -> None:
        it = self.nav_tree.currentItem()
        if not it or it.data(0, self.NODE_TYPE_ROLE) != "category":
            return
        cid = str(it.data(0, self.CATEGORY_ID_ROLE) or "")
        c = self.db.get_category(cid)
        if not c:
            return
        
        # ROOT 폴더는 삭제 불가
        if cid == ROOT_CATEGORY_ID:
            QMessageBox.warning(self, "Cannot Delete", "ROOT 폴더는 삭제할 수 없습니다.")
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
        save_ok = self._save_db_with_warning()
        if not save_ok:
            QMessageBox.critical(
                self,
                "Save Failed",
                "폴더 삭제 저장에 실패했습니다.\n\n"
                "변경사항이 저장되지 않았으므로 앱을 종료하면 폴더가 다시 나타날 수 있습니다."
            )
            return
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
            self.trace("아이템 생성 취소 - category_id 없음", "DEBUG")
            return
        name, ok = QInputDialog.getText(self, "Add Item", "Item name (in folder):", text="New Item")
        if not ok or not (name or "").strip():
            return
        self.trace(f"아이템 생성 시작 - 이름: {name.strip()}, category_id: {cid}", "DEBUG")
        it = self.db.add_item(name.strip(), cid)
        self.trace(f"아이템 생성 완료 - ID: {it.id}, category_id: {it.category_id}", "DEBUG")
        self.current_category_id = cid
        self.current_item_id = it.id
        self.current_page_index = 0
        self._save_ui_state()
        # 저장 성공 여부 확인
        self.trace("아이템 저장 시도...", "DEBUG")
        save_ok = self._save_db_with_warning()
        if not save_ok:
            # 저장 실패 시 아이템 롤백
            if it.id in self.db.items:
                del self.db.items[it.id]
            cat = self.db.categories.get(cid)
            if cat and it.id in cat.item_ids:
                cat.item_ids.remove(it.id)
            QMessageBox.critical(
                self,
                "Save Failed",
                f"아이템 '{name.strip()}' 생성은 되었지만 저장에 실패했습니다.\n\n"
                "아이템이 저장되지 않았으므로 앱을 종료하면 사라집니다.\n\n"
                "다시 시도하거나 파일이 잠겨있는지 확인해주세요."
            )
            return
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
        self._update_recent_items_list()  # 최근 작업 리스트 업데이트

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
        self._update_recent_items_list()  # 최근 작업 리스트 업데이트
        self._load_current_item_page_to_ui(clear_only=(not self.current_item_id))

    def _set_folder_url(self, cid: str) -> None:
        """폴더에 URL 설정"""
        cat = self.db.get_category(cid)
        if not cat:
            return
        
        url, ok = QInputDialog.getText(
            self,
            "Set Folder URL",
            "URL을 입력하세요:",
            text=cat.url if cat.url else ""
        )
        
        if ok:
            url = url.strip()
            # URL 유효성 검사 (간단한 검사)
            if url and not (url.startswith("http://") or url.startswith("https://")):
                url = "https://" + url
            
            cat.url = url
            self._save_db_with_warning()
            self._refresh_nav_tree(select_current=True)
    
    def _edit_folder_url(self, cid: str) -> None:
        """폴더 URL 편집"""
        self._set_folder_url(cid)  # 동일한 로직 사용
    
    def _remove_folder_url(self, cid: str) -> None:
        """폴더 URL 제거"""
        cat = self.db.get_category(cid)
        if not cat:
            return
        
        reply = QMessageBox.question(
            self,
            "Remove URL",
            f"'{cat.name}' 폴더의 URL을 제거하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            cat.url = ""
            self._save_db_with_warning()
            self._refresh_nav_tree(select_current=True)
    
    def _open_folder_url(self, cid: str) -> None:
        """폴더 URL을 브라우저로 열기"""
        cat = self.db.get_category(cid)
        if not cat or not cat.url or not cat.url.strip():
            QMessageBox.warning(self, "No URL", "이 폴더에 설정된 URL이 없습니다.")
            return
        
        url = cat.url.strip()
        # URL 유효성 검사
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"URL을 열 수 없습니다:\n{str(e)}")
    
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
        """리스트 적용 (기존 메서드 유지)"""
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
    
    def _toggle_list(self, kind: str) -> None:
        """리스트 토글: 리스트 안에 있으면 제거, 없으면 생성"""
        ed = self._active_rich_edit
        if ed is None:
            return
        cur = ed.textCursor()
        
        # 현재 리스트 확인
        current_list = cur.currentList()
        if current_list:
            # 리스트 안에 있으면 제거
            cur.beginEditBlock()
            try:
                # 리스트 포맷 제거
                fmt = QTextBlockFormat()
                cur.setBlockFormat(fmt)
                # 리스트에서 벗어나기
                cur.movePosition(cur.StartOfBlock)
                cur.movePosition(cur.EndOfBlock, cur.KeepAnchor)
                cur.insertText(cur.selectedText())
            except Exception:
                pass
            cur.endEditBlock()
        else:
            # 리스트가 없으면 생성
            style = QTextListFormat.ListDisc if kind == "bullet" else QTextListFormat.ListDecimal
            fmt = QTextListFormat(); fmt.setStyle(style)
            cur.beginEditBlock()
            try:
                cur.createList(fmt)
            except Exception:
                pass
            cur.endEditBlock()
        
        ed.setTextCursor(cur)
        ed.setFocus(Qt.MouseFocusReason)
        self._on_page_field_changed()
        self._sync_format_buttons()
    
    def _remove_list(self) -> None:
        """리스트 제거"""
        ed = self._active_rich_edit
        if ed is None:
            return
        cur = ed.textCursor()
        current_list = cur.currentList()
        if current_list:
            # 리스트의 모든 블록을 일반 텍스트로 변환
            cur.beginEditBlock()
            try:
                # 현재 블록부터 리스트의 끝까지 선택
                start_block = cur.block()
                cur.movePosition(cur.StartOfBlock)
                
                # 리스트의 모든 블록을 처리
                block = start_block
                while block.isValid():
                    block_list = block.textList()
                    if block_list != current_list:
                        break
                    # 블록의 텍스트를 가져와서 리스트 포맷 제거
                    block_cur = QTextCursor(block)
                    block_cur.select(block_cur.BlockUnderCursor)
                    text = block_cur.selectedText()
                    
                    # 리스트 포맷 제거
                    fmt = QTextBlockFormat()
                    block_cur.setBlockFormat(fmt)
                    block_cur.removeSelectedText()
                    block_cur.insertText(text)
                    
                    block = block.next()
                    if not block.isValid():
                        break
                
                # 현재 커서 위치 조정
                cur.setPosition(start_block.position())
            except Exception:
                pass
            cur.endEditBlock()
            ed.setTextCursor(cur)
            ed.setFocus(Qt.MouseFocusReason)
            self._on_page_field_changed()
            self._sync_format_buttons()
    
    def _indent_list(self) -> None:
        """리스트 들여쓰기 (간격을 작게 조정: 15px, 개별 항목만 이동)"""
        ed = self._active_rich_edit
        if ed is None:
            return
        cur = ed.textCursor()
        # QTextListFormat.indent()를 변경하면 같은 리스트의 모든 항목이 영향을 받으므로
        # QTextBlockFormat.leftMargin()만 사용하여 개별 항목의 들여쓰기 제어
        block_fmt = cur.blockFormat()
        left_margin = block_fmt.leftMargin()
        block_fmt.setLeftMargin(left_margin + 15)  # 작은 간격 (15px)
        cur.setBlockFormat(block_fmt)
        ed.setTextCursor(cur)
        ed.setFocus(Qt.MouseFocusReason)
        self._on_page_field_changed()
    
    def _outdent_list(self) -> None:
        """리스트 내어쓰기 (개별 항목만 이동)"""
        ed = self._active_rich_edit
        if ed is None:
            return
        cur = ed.textCursor()
        current_list = cur.currentList()
        block_fmt = cur.blockFormat()
        left_margin = block_fmt.leftMargin()
        
        if left_margin <= 0:
            # leftMargin이 0이고 리스트가 있으면 리스트 제거
            if current_list:
                self._remove_list()
            return
        
        # leftMargin만 조정하여 개별 항목만 내어쓰기
        block_fmt.setLeftMargin(max(0, left_margin - 15))  # 작은 간격만큼 감소 (15px)
        cur.setBlockFormat(block_fmt)
        ed.setTextCursor(cur)
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
        
        # 리스트 상태 동기화
        cur = ed.textCursor()
        current_list = cur.currentList()
        if current_list:
            fmt = current_list.format()
            style = fmt.style()
            # 리스트 스타일에 따라 버튼 활성화
            self.btn_bullets.blockSignals(True)
            self.btn_numbered.blockSignals(True)
            if style == QTextListFormat.ListDisc or style == QTextListFormat.ListCircle or style == QTextListFormat.ListSquare:
                self.btn_bullets.setChecked(True)
                self.btn_numbered.setChecked(False)
            elif style == QTextListFormat.ListDecimal or style == QTextListFormat.ListLowerAlpha or style == QTextListFormat.ListUpperAlpha:
                self.btn_bullets.setChecked(False)
                self.btn_numbered.setChecked(True)
            else:
                self.btn_bullets.setChecked(False)
                self.btn_numbered.setChecked(False)
            self.btn_bullets.blockSignals(False)
            self.btn_numbered.blockSignals(False)
        else:
            # 리스트가 없으면 둘 다 비활성화
            self.btn_bullets.blockSignals(True)
            self.btn_numbered.blockSignals(True)
            self.btn_bullets.setChecked(False)
            self.btn_numbered.setChecked(False)
            self.btn_bullets.blockSignals(False)
            self.btn_numbered.blockSignals(False)

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
        """상단 Description 토글 버튼 텍스트 및 아이콘 업데이트"""
        if hasattr(self, 'btn_toggle_desc'):
            self.btn_toggle_desc.blockSignals(True)
            self.btn_toggle_desc.setChecked(self._desc_visible)
            if self._desc_visible:
                # Description이 보일 때: 체크 표시
                self.btn_toggle_desc.setText("Description ✓")
            else:
                # Description이 숨겨져 있을 때: 오른쪽 화살표
                self.btn_toggle_desc.setText("Description ▶")
            self.btn_toggle_desc.blockSignals(False)
    
    def _update_checkbox_color(self, checkbox: QCheckBox, state: int) -> None:
        """체크박스 상태에 따라 질문 텍스트 색상 업데이트"""
        if state == Qt.Checked:
            checkbox.setStyleSheet("QCheckBox { color: #2D6BFF; }")
        else:
            checkbox.setStyleSheet("QCheckBox { color: #222222; }")
    
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
        # Tab/Shift+Tab 키로 리스트 들여쓰기/내어쓰기 지원
        if isinstance(obj, QTextEdit) and event.type() == QEvent.KeyPress:
            ed = self._active_rich_edit
            if ed is not None and obj is ed:
                if event.key() == Qt.Key_Tab:
                    cur = ed.textCursor()
                    current_list = cur.currentList()
                    block_fmt = cur.blockFormat()
                    # 리스트가 있거나 들여쓰기가 있으면 리스트 들여쓰기/내어쓰기 처리
                    if current_list or block_fmt.indent() > 0 or block_fmt.leftMargin() > 0:
                        if event.modifiers() & Qt.ShiftModifier:
                            # Shift+Tab: 내어쓰기
                            self._outdent_list()
                        else:
                            # Tab: 들여쓰기
                            self._indent_list()
                        return True
                elif event.key() == Qt.Key_Backtab:  # Shift+Tab은 Backtab으로도 감지됨
                    cur = ed.textCursor()
                    current_list = cur.currentList()
                    block_fmt = cur.blockFormat()
                    # 리스트가 있거나 들여쓰기가 있으면 내어쓰기
                    if current_list or block_fmt.indent() > 0 or block_fmt.leftMargin() > 0:
                        self._outdent_list()
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
