import flet as ft
from typing import Callable, Tuple, Optional

MIN_LEFT = 60
MIN_MID = 100
MIN_RIGHT = 60
TOTAL_FLEX = 300

class SplitterManager:
    def __init__(
        self, 
        page: ft.Page, 
        on_change: Callable[[int, int, int], None],
        on_save: Callable[[], None]
    ):
        self.page = page
        self.on_change = on_change
        self.on_save = on_save
        self.drag_base: Optional[Tuple[int, float, int, int, int]] = None
        self.left = 100
        self.mid = 100
        self.right = 100

    def set_values(self, l: int, m: int, r: int):
        self.left, self.mid, self.right = l, m, r

    def normalize(self):
        L = max(MIN_LEFT, self.left)
        M = max(MIN_MID, self.mid)
        R = max(MIN_RIGHT, self.right)
        s = max(1, L + M + R)
        if s != TOTAL_FLEX:
            k = TOTAL_FLEX / s
            L = max(MIN_LEFT, int(round(L * k)))
            M = max(MIN_MID, int(round(M * k)))
            R = max(MIN_RIGHT, TOTAL_FLEX - L - M)
        self.left, self.mid, self.right = L, M, R

    def create_splitter(self, which: int) -> ft.Container:
        bar = ft.Container(
            width=4,
            bgcolor=ft.Colors.with_opacity(0.45, ft.Colors.BLUE_GREY_800),
            border_radius=999,
            expand=True,
        )

        def on_start(e: ft.DragStartEvent):
            self.drag_base = (which, e.global_x or 0.0, self.left, self.mid, self.right)

        def on_update(e: ft.DragUpdateEvent):
            if not self.drag_base:
                return
            w_id, x0, L0, M0, R0 = self.drag_base
            dx = (e.global_x or 0.0) - x0
            w_total = getattr(self.page, "window_width", None) or 1200
            px_per_flex = max(2.0, w_total / TOTAL_FLEX)
            raw_delta = int(round(dx / px_per_flex))

            if w_id == 1:
                d_min = MIN_LEFT - L0
                d_max = M0 - MIN_MID
            else:
                d_min = MIN_MID - M0
                d_max = R0 - MIN_RIGHT

            if d_min > d_max:
                return

            flex_delta = max(d_min, min(raw_delta, d_max))

            if w_id == 1:
                L, M, R = L0 + flex_delta, M0 - flex_delta, R0
            else:
                L, M, R = L0, M0 + flex_delta, R0 - flex_delta
            
            self.apply_absolute(L, M, R)

        def on_end(e: ft.DragEndEvent):
            self.drag_base = None
            self.normalize()
            self.on_save()

        gd = ft.GestureDetector(
            content=bar,
            mouse_cursor=ft.MouseCursor.RESIZE_COLUMN,
            on_horizontal_drag_start=on_start,
            on_horizontal_drag_update=on_update,
            on_horizontal_drag_end=on_end,
        )
        return ft.Container(content=gd, padding=0)

    def apply_absolute(self, L: int, M: int, R: int):
        L = max(MIN_LEFT, L)
        M = max(MIN_MID, M)
        R = max(MIN_RIGHT, R)
        s = L + M + R
        if s != TOTAL_FLEX:
            k = TOTAL_FLEX / s
            L = max(MIN_LEFT, int(round(L * k)))
            M = max(MIN_MID, int(round(M * k)))
            R = max(MIN_RIGHT, TOTAL_FLEX - L - M)
        self.left, self.mid, self.right = L, M, R
        self.on_change(L, M, R)