확인했습니다. 공유해주신 코드는 Trader Chart Note App (PyQt5) v0.6.0 (2026-01-01) 기준의 “마지막 작업본”으로, 말씀하신 핵심 요구사항들이 코드 레벨에서 다음처럼 반영돼 있습니다.

v0.6.0 반영 사항이 들어간 지점 요약
1) 좌측 트리: Folder(Category) / Item 구조

NoteDB 데이터 모델:

Category(id, name, parent_id, child_ids, item_ids)

Item(id, name, category_id, pages, last_page_index)

root_category_ids로 루트 폴더 트리 유지

UI 트리 구성:

_refresh_nav_tree()에서 Category → Item → Child Category DFS로 QTreeWidgetItem 생성

역할(Role):

NODE_TYPE_ROLE = "category" / "item"

CATEGORY_ID_ROLE, ITEM_ID_ROLE로 ID 매핑

2) Drag&Drop 제거 + Up/Down 이동만

트리 자체 Drag&Drop 관련 플래그/핸들링이 없고,

이동은 DB 레벨에서 인접 swap:

move_category_sibling(cid, direction)

move_item_sibling(iid, direction)

UI 버튼 및 컨텍스트 메뉴에서 위 함수만 호출하도록 구성

3) Folder 선택 시 우측 편집 영역 “완전 숨김(빈 캔버스)” 처리

핵심은 content_stack: QStackedWidget

0 = editor(page_splitter 전체)

1 = placeholder("Select an item to view")

트리 선택 변경 로직:

_on_tree_selection_changed()

category 선택 시:

self.current_item_id = ""

self._show_placeholder(True)

_load_current_item_page_to_ui(clear_only=True)로 우측 필드/뷰어 정리

item 선택 시:

self._show_placeholder(False)

_load_current_item_page_to_ui()로 로드

4) Trace(디버그 출력) 영역 유지 + 토글/사이즈 저장

right_vsplit = QSplitter(Qt.Vertical) 상단 content + 하단 trace 구조

trace_visible 상태 및 sizes 저장:

self.db.ui_state["trace_visible"]

self.db.ui_state["right_vsplit_sizes"]

Hide/Show 버튼과 _set_trace_visible()로 동작
