import flet as ft
import re
import threading
import sqlite3
import logging
import urllib.parse
from typing import List, Optional

from app.database import Database
from app.services.ai_client import OpenRouterClient
from app.services.exporter import export_pdf_markdown, markdown_to_text
from app.utils.common import Debouncer
from app.ui.layout import SplitterManager
from app.ui import dialogs

log = logging.getLogger("smartnotes.ui")

class SmartNotesApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.db = Database()
        self.api = OpenRouterClient(self.db.get_setting("openrouter_api_key"))

        self.current_folder_id: Optional[int] = None
        self.selected_note_id: Optional[int] = None
        self.search_query: str = ""
        self.filter_tag_ids: List[int] = []

        self.splitter = SplitterManager(
            self.page,
            self._update_layout_flex,
            self._save_flex
        )
        self._init_flex()

        self.left_box: ft.Ref[ft.Container] = ft.Ref[ft.Container]()
        self.mid_box: ft.Ref[ft.Container] = ft.Ref[ft.Container]()
        self.right_box: ft.Ref[ft.Container] = ft.Ref[ft.Container]()

        self.ai_menu_btn: Optional[ft.PopupMenuButton] = None
        self.ai_tags_btn: Optional[ft.ElevatedButton] = None
        self.ai_title_btn: Optional[ft.ElevatedButton] = None
        self.ai_sum_btn: Optional[ft.ElevatedButton] = None

        self.folders_list: ft.ListView = ft.ListView(expand=True, spacing=4, padding=4, auto_scroll=False)
        self.notes_list: ft.ListView = ft.ListView(expand=True, spacing=2, padding=4, auto_scroll=False)

        # Container for Editor or Preview
        self.editor_preview_host = ft.Container(expand=True)
        
        self.title_field = ft.TextField()
        self.content_field = ft.TextField()
        self.preview_switch = ft.Switch()
        self.note_tags_wrap = ft.Row(spacing=4, run_spacing=6, wrap=True)
        self.add_tag_field = ft.TextField(
            hint_text="Добавить тег и Enter",
            on_submit=lambda e: self._add_tag_from_field(),
        )
        self.search_field = ft.TextField()

        self.autosave = Debouncer(600, self._save_current_note)
        self.dialog_refs = {}

        self._build_page()
        self._load_folders()
        self._reload_notes()

    def _init_flex(self):
        def read_int(name: str, default: int) -> int:
            try:
                return int(self.db.get_setting(name) or default)
            except Exception:
                return default

        L = read_int("flex_left", 100)
        M = read_int("flex_mid", 100)
        R = read_int("flex_right", 100)
        s = max(1, L + M + R)
        if s <= 40:
            L, M, R = L * 10, M * 10, R * 10
        self.splitter.set_values(L, M, R)
        self.splitter.normalize()
        self._save_flex(commit=False)

    def _save_flex(self, commit: bool = True):
        if commit:
            self.db.set_setting("flex_left", str(self.splitter.left))
            self.db.set_setting("flex_mid", str(self.splitter.mid))
            self.db.set_setting("flex_right", str(self.splitter.right))

    def _update_layout_flex(self, l: int, m: int, r: int):
        if self.left_box.current and self.mid_box.current and self.right_box.current:
            self.left_box.current.expand = l
            self.mid_box.current.expand = m
            self.right_box.current.expand = r
            self.page.update()

    def _build_page(self):
        self.page.title = "SmartNotes"
        self.page.window_min_width = 1000
        self.page.window_min_height = 680
        self.page.on_keyboard_event = self._on_key
        self.page.theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE_GREY)
        self.page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.BLUE_GREY)
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#020617"
        self.page.padding = 0

        layout_btn = ft.IconButton(
            icon=ft.Icons.SPACE_DASHBOARD,
            tooltip="Макет панелей",
            on_click=lambda e: self._open_layout_dialog(),
        )

        appbar_title = ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    width=32,
                    height=32,
                    border_radius=16,
                    bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.BLUE_GREY_700),
                    alignment=ft.alignment.center,
                    content=ft.Icon(ft.Icons.LIGHTBULB, size=18, color=ft.Colors.WHITE),
                ),
                ft.Column(
                    spacing=0,
                    controls=[
                        ft.Text("SmartNotes", weight=ft.FontWeight.BOLD, size=18, color=ft.Colors.WHITE),
                        ft.Text(
                            "Умные заметки с Markdown и ИИ",
                            size=11,
                            color=ft.Colors.with_opacity(0.8, ft.Colors.WHITE),
                        ),
                    ],
                ),
            ],
        )

        self.page.appbar = ft.AppBar(
            title=appbar_title,
            center_title=False,
            bgcolor=ft.Colors.BLUE_GREY_900,
            elevation=2,
            actions=[
                layout_btn,
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="Обновить",
                    on_click=lambda e: self._refresh_all(),
                ),
                ft.PopupMenuButton(
                    tooltip="Действия",
                    items=[
                        ft.PopupMenuItem(text="Импорт .txt/.md", on_click=lambda e: self._import_note(), icon=ft.Icons.FILE_UPLOAD),
                        ft.PopupMenuItem(text="Экспорт .txt", on_click=lambda e: self._export_note("txt"), icon=ft.Icons.DESCRIPTION),
                        ft.PopupMenuItem(text="Экспорт .md", on_click=lambda e: self._export_note("md"), icon=ft.Icons.CODE),
                        ft.PopupMenuItem(text="Экспорт PDF", on_click=lambda e: self._export_note("pdf"), icon=ft.Icons.PICTURE_AS_PDF),
                        ft.PopupMenuItem(text="Статистика", on_click=lambda e: self._show_stats(), icon=ft.Icons.INSIGHTS),
                        ft.PopupMenuItem(text="Справка Markdown", on_click=lambda e: self._show_markdown_help(), icon=ft.Icons.HELP_OUTLINE),
                        ft.PopupMenuItem(text="Настройки", on_click=lambda e: self._open_settings(), icon=ft.Icons.SETTINGS),
                    ],
                ),
            ],
        )

        tags_btn = ft.IconButton(
            icon=ft.Icons.LABEL_OUTLINE,
            tooltip="Фильтр по тегам",
            on_click=self._open_tags_filter_dialog,
        )
        self.search_field = ft.TextField(
            hint_text="Поиск...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=self._on_search_change,
            dense=True,
            filled=True,
            border_radius=20,
            expand=True,
        )
        search_row = ft.Row(
            controls=[self.search_field, tags_btn],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self.title_field = ft.TextField(
            hint_text="Заголовок",
            on_change=lambda e: self._on_editor_change(),
            text_style=ft.TextStyle(weight=ft.FontWeight.BOLD),
        )
        # Очистили подсказку
        self.content_field = ft.TextField(
            hint_text="Начните писать...",
            multiline=True,
            min_lines=10,
            expand=True,
            on_change=lambda e: self._on_editor_change(),
            border_radius=8,
        )
        self.preview_switch = ft.Switch(
            label="Предпросмотр Markdown",
            value=False,
            on_change=lambda e: self._update_preview(),
        )
        ai_row = self._build_ai_buttons()

        subtle_text_color = ft.Colors.with_opacity(0.75, ft.Colors.WHITE)
        left_panel = ft.Column(
            [
                ft.Row([ft.Row([ft.Icon(ft.Icons.FOLDER, size=18), ft.Text("Папки", weight=ft.FontWeight.BOLD)], spacing=6)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text("Группируйте заметки в папки", size=11, color=subtle_text_color),
                ft.ElevatedButton("Новая папка", icon=ft.Icons.CREATE_NEW_FOLDER, on_click=lambda e: self._create_folder(), style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=20))),
                ft.Divider(color=ft.Colors.with_opacity(0.35, ft.Colors.WHITE)),
                self.folders_list,
            ],
            expand=True, spacing=8,
        )
        middle_panel = ft.Column(
            [
                ft.Row([ft.Row([ft.Icon(ft.Icons.NOTE, size=18), ft.Text("Заметки", weight=ft.FontWeight.BOLD)], spacing=6)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text("Быстрый поиск и управление заметками", size=11, color=subtle_text_color),
                search_row,
                ft.ElevatedButton("Новая заметка (Ctrl+N)", icon=ft.Icons.NOTE_ADD, on_click=lambda e: self._create_note(), style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=20))),
                ft.Divider(color=ft.Colors.with_opacity(0.35, ft.Colors.WHITE)),
                self.notes_list,
            ],
            expand=True, spacing=8,
        )
        right_panel = ft.Column(
            [
                ft.Row([ft.Row([ft.Icon(ft.Icons.EDIT_NOTE, size=20), ft.Text("Редактор", weight=ft.FontWeight.BOLD)], spacing=6)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text("Пишите в Markdown, отмечайте задачи, добавляйте теги", size=11, color=subtle_text_color),
                self.title_field,
                ft.Row([self.preview_switch], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.editor_preview_host,
                ft.Divider(color=ft.Colors.with_opacity(0.35, ft.Colors.WHITE)),
                ft.Text("Теги", weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                self.note_tags_wrap,
                self.add_tag_field,
                ft.Divider(color=ft.Colors.with_opacity(0.35, ft.Colors.WHITE)),
                ft.Text("Инструменты ИИ", size=11, color=subtle_text_color),
                ai_row,
            ],
            expand=True, spacing=8,
        )

        border_color = ft.Colors.with_opacity(0.35, ft.Colors.BLUE_GREY_700)
        panel_shadow = ft.BoxShadow(blur_radius=18, color=ft.Colors.with_opacity(0.35, ft.Colors.BLACK), offset=ft.Offset(0, 6))

        def wrap_panel(content):
            return ft.Container(
                content=content, padding=12, bgcolor="#050816",
                border_radius=14, border=ft.border.all(1, border_color), shadow=panel_shadow,
            )

        left_box = ft.Container(wrap_panel(left_panel), ref=self.left_box, expand=self.splitter.left, padding=ft.Padding(12, 12, 6, 12))
        mid_box = ft.Container(wrap_panel(middle_panel), ref=self.mid_box, expand=self.splitter.mid, padding=ft.Padding(6, 12, 6, 12))
        right_box = ft.Container(wrap_panel(right_panel), ref=self.right_box, expand=self.splitter.right, padding=ft.Padding(6, 12, 12, 12))

        split1 = self.splitter.create_splitter(1)
        split2 = self.splitter.create_splitter(2)

        row = ft.Row(
            controls=[left_box, split1, mid_box, split2, right_box],
            expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

        self.page.controls.clear()
        self.page.add(row)

        self.loading_overlay = ft.Container(
            visible=False,
            alignment=ft.alignment.center,
            bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLACK),
            content=ft.Container(
                padding=20, border_radius=16, bgcolor="#020617",
                border=ft.border.all(1, border_color), shadow=panel_shadow,
                content=ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=12,
                    controls=[
                        ft.ProgressRing(),
                        ft.Text("Выполняется...", weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        ft.Text("Подождите, ИИ или операция с файлом ещё не завершены", size=11, color=subtle_text_color, text_align=ft.TextAlign.CENTER),
                    ],
                ),
            ),
        )
        self.fp_open = ft.FilePicker(on_result=self._on_import_result)
        self.fp_save = ft.FilePicker(on_result=self._on_export_result)
        self.page.overlay.clear()
        self.page.overlay.extend([self.fp_open, self.fp_save, self.loading_overlay])

        self.page.update()
        self._update_preview()

    def _build_ai_buttons(self) -> ft.Row:
        disabled = not self.api.available()
        tip = "Добавьте OpenRouter API-ключ в Настройках" if disabled else "ИИ-инструменты"

        self.ai_menu_btn = ft.PopupMenuButton(
            icon=ft.Icons.BUILD, tooltip=tip, disabled=disabled,
            items=[
                ft.PopupMenuItem(text="Исправить грамматику", on_click=lambda e: self._ai_improve("Fix grammar"), icon=ft.Icons.SPELLCHECK),
                ft.PopupMenuItem(text="Сделать более официальным", on_click=lambda e: self._ai_improve("More formal"), icon=ft.Icons.WORK),
                ft.PopupMenuItem(text="Упростить язык", on_click=lambda e: self._ai_improve("Simplify"), icon=ft.Icons.LIGHT_MODE),
            ],
        )
        self.ai_tags_btn = ft.ElevatedButton("Предложить теги", icon=ft.Icons.AUTO_AWESOME, disabled=disabled, tooltip=tip, on_click=lambda e: self._ai_suggest_tags())
        self.ai_title_btn = ft.ElevatedButton("Сгенерировать заголовок", icon=ft.Icons.TEXT_FIELDS, disabled=disabled, tooltip=tip, on_click=lambda e: self._ai_generate_title())
        self.ai_sum_btn = ft.ElevatedButton("Суммаризация", icon=ft.Icons.TEXT_SNIPPET, disabled=disabled, tooltip=tip, on_click=lambda e: self._ai_summarize())

        return ft.Row([self.ai_menu_btn, self.ai_tags_btn, self.ai_title_btn, self.ai_sum_btn], wrap=True, spacing=8, run_spacing=8)

    def _update_ai_buttons_state(self):
        enabled = self.api.available()
        tip = "ИИ-инструменты" if enabled else "Добавьте OpenRouter API-ключ в Настройках"
        for btn in [self.ai_menu_btn, self.ai_tags_btn, self.ai_title_btn, self.ai_sum_btn]:
            if btn:
                btn.disabled = not enabled
                btn.tooltip = tip
        self.page.update()

    def _update_preview(self):
        if not self.preview_switch.value:
            self.editor_preview_host.content = self.content_field
            self.page.update()
            return
        
        raw_content = self.content_field.value or ""
        lines = raw_content.splitlines()
        
        task_pattern = re.compile(r"^(\s*)-\s\[([ xX])\]\s(.*)$")
        
        controls = []
        current_md_block = []

        def flush_md():
            if current_md_block:
                text = "\n".join(current_md_block)
                processed_text = self._preprocess_markdown(text)
                controls.append(
                    ft.Markdown(
                        value=processed_text,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                        code_theme="github",
                        selectable=True,
                        on_tap_link=self._on_markdown_link_click,
                    )
                )
                current_md_block.clear()

        for idx, line in enumerate(lines):
            m = task_pattern.match(line)
            if m:
                flush_md()
                indent, mark, text = m.groups()
                is_checked = mark.lower() == "x"
                controls.append(
                    ft.Container(
                        content=ft.Checkbox(
                            label=text,
                            value=is_checked,
                            on_change=lambda e, i=idx: self._toggle_task_line(i)
                        ),
                        padding=ft.Padding(left=len(indent)*8, top=0, right=0, bottom=0)
                    )
                )
            else:
                current_md_block.append(line)
        
        flush_md()
        
        self.editor_preview_host.content = ft.Column(
            controls=controls,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=2
        )
        self.page.update()

    def _preprocess_markdown(self, text: str) -> str:
        def replace_link(match):
            title = match.group(1)
            url_part = urllib.parse.quote(title)
            return f"[{title}](note:{url_part})"
        return re.sub(r"\[\[(.*?)\]\]", replace_link, text)

    def _on_markdown_link_click(self, e):
        url = e.data
        if url.startswith("note:"):
            encoded_part = url[5:]
            note_title = urllib.parse.unquote(encoded_part)
            self._navigate_to_wiki_link(note_title)
        else:
            self.page.launch_url(url)

    def _navigate_to_wiki_link(self, title: str):
        nid = self.db.get_note_id_by_title(title)
        if nid:
            self._select_note(nid)
        else:
            self._offer_create_wiki_note(title)

    def _offer_create_wiki_note(self, title: str):
        def create(e):
            self._close_dialog(dlg)
            new_id = self.db.create_note(self.current_folder_id, title=title)
            self._reload_notes()
            self._select_note(new_id)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Заметка не найдена"),
            content=ft.Text(f"Создать новую заметку с названием '{title}'?"),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: self._close_dialog(dlg)),
                ft.ElevatedButton("Создать", on_click=create),
            ], actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dlg)

    def _toggle_task_line(self, i: int):
        lines = (self.content_field.value or "").splitlines()
        if 0 <= i < len(lines):
            line = lines[i]
            if "- [ ]" in line:
                line = line.replace("- [ ]", "- [x]", 1)
            elif "- [x]" in line:
                line = line.replace("- [x]", "- [ ]", 1)
            elif "- [X]" in line:
                line = line.replace("- [X]", "- [ ]", 1)
            lines[i] = line
            self.content_field.value = "\n".join(lines)
            self._save_current_note()
            self._update_preview()

    def _load_folders(self):
        if not self.folders_list:
            return
        self.folders_list.controls.clear()
        self.folders_list.controls.append(
            ft.ListTile(
                leading=ft.Icon(ft.Icons.ALL_INBOX, color=ft.Colors.WHITE),
                title=ft.Text("Все заметки", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, color=ft.Colors.WHITE),
                selected=self.current_folder_id is None,
                selected_color=ft.Colors.ON_PRIMARY_CONTAINER,
                selected_tile_color=ft.Colors.with_opacity(0.35, ft.Colors.PRIMARY_CONTAINER),
                on_click=lambda e: self._select_folder(None),
                dense=True,
            )
        )
        for f in self.db.list_folders():
            fid = f["id"]
            is_selected = self.current_folder_id == fid
            actions = ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.DRIVE_FILE_RENAME_OUTLINE, tooltip="Переименовать", on_click=lambda e, fid=fid: self._rename_folder(fid), icon_size=18),
                    ft.IconButton(icon=ft.Icons.DELETE, tooltip="Удалить", on_click=lambda e, fid=fid: self._delete_folder(fid), icon_size=18),
                ], spacing=0, tight=True,
            )
            self.folders_list.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.FOLDER_OPEN if is_selected else ft.Icons.FOLDER, color=ft.Colors.WHITE),
                    title=ft.Text(f["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, color=ft.Colors.WHITE),
                    selected=is_selected,
                    selected_color=ft.Colors.ON_PRIMARY_CONTAINER,
                    selected_tile_color=ft.Colors.with_opacity(0.35, ft.Colors.PRIMARY_CONTAINER),
                    on_click=lambda e, fid=fid: self._select_folder(fid),
                    trailing=actions, dense=True,
                )
            )
        self.folders_list.update()

    def _reload_notes(self):
        if not self.notes_list:
            return
        self.notes_list.controls.clear()
        for n in self.db.search_notes(self.current_folder_id, self.search_query, self.filter_tag_ids):
            nid = n["id"]
            actions = ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip="Переместить", on_click=lambda e, nid=nid: self._move_note_dialog(nid), icon_size=18),
                    ft.IconButton(icon=ft.Icons.DELETE, tooltip="Удалить", on_click=lambda e, nid=nid: self._delete_note(nid), icon_size=18),
                ], spacing=0, tight=True,
            )
            title_text = n["title"] if n["title"].strip() else "(без заголовка)"
            subtitle_text = ", ".join([t["name"] for t in n["tags"]])
            leading_icon = ft.Icons.CHECKLIST if subtitle_text.strip() else ft.Icons.DESCRIPTION
            self.notes_list.controls.append(
                ft.ListTile(
                    leading=ft.Icon(leading_icon, color=ft.Colors.WHITE),
                    title=ft.Text(title_text, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, color=ft.Colors.WHITE),
                    subtitle=ft.Text(subtitle_text, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, color=ft.Colors.with_opacity(0.75, ft.Colors.WHITE)),
                    selected=(self.selected_note_id == nid),
                    selected_color=ft.Colors.ON_SECONDARY_CONTAINER,
                    selected_tile_color=ft.Colors.with_opacity(0.35, ft.Colors.SECONDARY_CONTAINER),
                    on_click=lambda e, nid=nid: self._select_note(nid),
                    trailing=actions, dense=True,
                )
            )
        self.notes_list.update()

    def _select_folder(self, folder_id: Optional[int]):
        self.current_folder_id = folder_id
        self._load_folders()
        self._reload_notes()

    def _create_folder(self):
        def confirm(name: str):
            name = name.strip()
            if not name:
                self._snack("Введите название папки")
                return
            try:
                self.db.create_folder(name)
                self._close_dialog(dlg)
                self._load_folders()
                self.page.update()
            except sqlite3.IntegrityError:
                self._snack("Папка с таким именем уже существует")
            except Exception as ex:
                self._snack(str(ex))

        dlg = dialogs.create_folder_dialog(confirm, lambda: self._close_dialog(dlg))
        self._open_dialog(dlg)

    def _rename_folder(self, folder_id: int):
        def confirm(name: str):
            name = name.strip()
            if not name:
                self._snack("Введите новое имя")
                return
            try:
                self.db.rename_folder(folder_id, name)
                self._close_dialog(dlg)
                self._load_folders()
                self._reload_notes()
                self.page.update()
            except sqlite3.IntegrityError:
                self._snack("Папка с таким именем уже существует")
            except Exception as ex:
                self._snack(str(ex))

        dlg = dialogs.rename_folder_dialog(confirm, lambda: self._close_dialog(dlg))
        self._open_dialog(dlg)

    def _delete_folder(self, folder_id: int):
        def confirm():
            try:
                self.db.delete_folder(folder_id)
                self._close_dialog(dlg)
                if self.current_folder_id == folder_id:
                    self.current_folder_id = None
                self._load_folders()
                self._reload_notes()
                self.page.update()
            except Exception as ex:
                self._snack(str(ex))

        dlg = dialogs.delete_folder_dialog(confirm, lambda: self._close_dialog(dlg))
        self._open_dialog(dlg)

    def _create_note(self):
        nid = self.db.create_note(self.current_folder_id)
        self._reload_notes()
        self._select_note(nid)

    def _select_note(self, note_id: int):
        self.selected_note_id = note_id
        n = self.db.get_note(note_id)
        if n:
            self.title_field.value = n["title"]
            self.content_field.value = n["content"]
            self._load_note_tags()
            self._update_preview()
        self._reload_notes()

    def _delete_note(self, note_id: int):
        self.db.delete_note(note_id)
        if self.selected_note_id == note_id:
            self.selected_note_id = None
            self.title_field.value = ""
            self.content_field.value = ""
            self.note_tags_wrap.controls.clear()
            self.note_tags_wrap.update()
        self._reload_notes()
        self._update_preview()

    def _move_note_dialog(self, note_id: int):
        folders = [dict(id=f["id"], name=f["name"]) for f in self.db.list_folders()]
        
        def confirm(val: str):
            if val in (None, "", "__ALL__"):
                to_folder = None
            else:
                try:
                    to_folder = int(val)
                except Exception:
                    to_folder = None
            self.db.move_note(note_id, to_folder)
            self._close_dialog(dlg)
            self._reload_notes()

        dlg = dialogs.move_note_dialog(folders, confirm, lambda: self._close_dialog(dlg))
        self._open_dialog(dlg)

    def _on_editor_change(self):
        self.autosave.call()

    def _save_current_note(self):
        if not self.selected_note_id:
            return
        self.db.update_note(
            self.selected_note_id,
            self.title_field.value or "",
            self.content_field.value or "",
            self.current_folder_id,
        )
        self._reload_notes()
        self._update_preview()

    def _load_note_tags(self):
        self.note_tags_wrap.controls.clear()
        if not self.selected_note_id:
            self.note_tags_wrap.update()
            return
        for t in self.db.list_note_tags(self.selected_note_id):
            tid = t["id"]
            self.note_tags_wrap.controls.append(
                ft.Chip(
                    label=ft.Text(t["name"], color=ft.Colors.WHITE),
                    on_delete=lambda e, tid=tid: self._remove_tag(tid),
                )
            )
        self.note_tags_wrap.update()

    def _remove_tag(self, tag_id: int):
        if not self.selected_note_id:
            return
        cur = [t["name"] for t in self.db.list_note_tags(self.selected_note_id)]
        id_to_name = {t["id"]: t["name"] for t in self.db.all_tags()}
        name = id_to_name.get(tag_id)
        if name and name in cur:
            cur.remove(name)
        self.db.set_note_tags(self.selected_note_id, cur)
        self._load_note_tags()
        self._reload_notes()

    def _add_tag_from_field(self):
        name = (self.add_tag_field.value or "").strip()
        if not name or not self.selected_note_id:
            return
        cur = [t["name"] for t in self.db.list_note_tags(self.selected_note_id)]
        if name not in cur:
            cur.append(name)
        self.db.set_note_tags(self.selected_note_id, cur)
        self.add_tag_field.value = ""
        self.add_tag_field.update()
        self._load_note_tags()
        self._reload_notes()

    def _open_tags_filter_dialog(self, e=None):
        all_tags = self.db.all_tags()
        selected = set(self.filter_tag_ids)

        def toggle(ev, tid: int):
            if ev.control.value:
                selected.add(tid)
            else:
                selected.discard(tid)

        checks = []
        for t in all_tags:
            tid = t["id"]
            checks.append(ft.Checkbox(
                label=f"{t['name']} ({t['usage_count']})",
                value=(tid in selected),
                on_change=lambda ev, tid=tid: toggle(ev, tid),
            ))
        col = ft.Column(checks, scroll=ft.ScrollMode.AUTO, height=400, width=420)
        
        def apply():
            self.filter_tag_ids = list(selected)
            self._close_dialog(dlg)
            self._reload_notes()

        def reset():
            self.filter_tag_ids = []
            self._close_dialog(dlg)
            self._reload_notes()

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Фильтр по тегам"), content=col,
            actions=[
                ft.TextButton("Сброс", on_click=lambda e: reset()),
                ft.ElevatedButton("Применить", on_click=lambda e: apply()),
            ], actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self._open_dialog(dlg)

    def _on_search_change(self, e):
        self.search_query = e.control.value or ""
        self._reload_notes()

    def _import_note(self):
        self.fp_open.pick_files(allow_multiple=False, allowed_extensions=["txt", "md"])

    def _on_import_result(self, e: ft.FilePickerResultEvent):
        if not e.files:
            return
        f = e.files[0]
        try:
            with open(f.path, "r", encoding="utf-8") as fh:
                data = fh.read()
            nid = self.db.create_note(self.current_folder_id)
            title = ""
            for line in data.splitlines():
                if line.strip():
                    title = line.strip()[:120]
                    break
            self.db.update_note(nid, title, data, self.current_folder_id)
            self._reload_notes()
            self._select_note(nid)
        except Exception as ex:
            self._snack(str(ex))

    def _export_note(self, kind: str):
        if not self.selected_note_id:
            self._snack("Нет выбранной заметки")
            return
        ext = "txt" if kind == "txt" else "md" if kind == "md" else "pdf"
        self.fp_save.save_file(file_name=f"note.{ext}")

    def _on_export_result(self, e: ft.FilePickerResultEvent):
        if not e.path:
            return
        path = e.path
        if not self.selected_note_id:
            return
        n = self.db.get_note(self.selected_note_id)
        if not n:
            return
        try:
            if path.lower().endswith(".pdf"):
                export_pdf_markdown(path, n["title"], n["content"])
            else:
                content = n["content"]
                if path.lower().endswith(".txt"):
                    content = markdown_to_text(content)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
            self._snack("Экспорт выполнен")
        except Exception as ex:
            self._snack(str(ex))

    def _get_text_for_ai(self) -> str:
        return self.content_field.value or ""

    def _ai_improve(self, mode: str):
        if not self.api.available():
            return
        if not self.selected_note_id:
            self._snack("Сначала выберите или создайте заметку (Ctrl+N)")
            return
            
        src = self._get_text_for_ai()

        def task():
            out = self.api.improve_text(src, mode)
            if not out:
                self._snack("Не удалось улучшить текст")
                return
            self.content_field.value = out
            self.content_field.update()
            self._save_current_note()

        self._with_loading(task)

    def _ai_suggest_tags(self):
        if not self.api.available():
            return
        if not self.selected_note_id:
            self._snack("Сначала выберите или создайте заметку (Ctrl+N)")
            return
            
        text = (self.title_field.value or "") + "\n\n" + (self.content_field.value or "")

        def task():
            tags = self.api.suggest_tags(text, max_tags=5)
            if not tags:
                self._snack("Теги не найдены")
                return
            checks = [ft.Checkbox(label=t, value=True, data=t) for t in tags]
            col = ft.Column(checks, scroll=ft.ScrollMode.AUTO, height=300, width=400)
            
            def accept():
                self._close_dialog(dlg)
                if not self.selected_note_id:
                    return
                cur = [t["name"] for t in self.db.list_note_tags(self.selected_note_id)]
                for t in [c.data for c in checks if c.value]:
                    if t not in cur:
                        cur.append(t)
                self.db.set_note_tags(self.selected_note_id, cur)
                self._load_note_tags()
                self._reload_notes()

            dlg = ft.AlertDialog(
                modal=True, title=ft.Text("Предложенные теги"), content=col,
                actions=[
                    ft.TextButton("Отмена", on_click=lambda e: self._close_dialog(dlg)),
                    ft.ElevatedButton("Добавить", on_click=lambda e: accept()),
                ], actions_alignment=ft.MainAxisAlignment.END,
            )
            self._open_dialog(dlg)

    def _ai_generate_title(self):
        if not self.api.available():
            return
        if not self.selected_note_id:
            self._snack("Сначала выберите или создайте заметку (Ctrl+N)")
            return
        if (self.title_field.value or "").strip():
            self._snack("Заголовок уже задан")
            return
        text = self._get_text_for_ai()

        def task():
            t = self.api.generate_title(text, max_len=80)
            if not t:
                self._snack("Не удалось сгенерировать заголовок")
                return
            self.title_field.value = t.strip().strip('"“”')
            self.title_field.update()
            self._save_current_note()

        self._with_loading(task)

    def _ai_summarize(self):
        if not self.api.available():
            return
        if not self.selected_note_id:
            self._snack("Сначала выберите или создайте заметку (Ctrl+N)")
            return
        text = self._get_text_for_ai()

        def task():
            s = self.api.summarize(text, max_sentences=3)
            if not s:
                self._snack("Не удалось создать суммаризацию")
                return
            new_content = f"## Summary\n\n{s}\n\n" + (self.content_field.value or "")
            self.content_field.value = new_content
            self.content_field.update()
            self._save_current_note()

        self._with_loading(task)
    
    def _show_markdown_help(self):
        help_text = """
### 📝 Форматирование текста
| Результат | Как написать |
| :--- | :--- |
| **Жирный** | `**Текст**` |
| *Курсив* | `*Текст*` |
| ~~Зачеркнутый~~ | `~~Текст~~` |

### 🏷 Заголовки
Используйте решетку и пробел в начале строки:
# H1 (`# Текст`)
## H2 (`## Текст`)
### H3 (`### Текст`)

### ✅ Списки и Задачи
**Списки:** Начинайте строку с `- ` (дефис и пробел).

**Чек-листы (Задачи):**
- [ ] Не выполнено (`- [ ] Текст`)
- [x] Выполнено (`- [x] Текст`)
*Важно: соблюдайте пробелы внутри скобок!*

### 🔗 Другое
**Wiki-ссылки:**
`[[Название заметки]]` — связь с другой заметкой.

**Разделитель:**
`---` (три дефиса на отдельной строке)
        """
        dlg = ft.AlertDialog(
            title=ft.Text("Справка по Markdown"),
            content=ft.Container(
                content=ft.Column(
                    [ft.Markdown(
                        value=help_text, 
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB
                    )],
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=600,
                height=500,
            ),
            actions=[
                ft.TextButton("Закрыть", on_click=lambda e: self._close_dialog(dlg))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dlg)

    def _open_settings(self):
        current_key = self.api.api_key

        def run_test(key_val: str):
            self.api.set_key(key_val.strip())
            refs = self.dialog_refs
            refs["check_btn"].disabled = True
            refs["progress"].visible = True
            refs["status_text"].value = ""
            self.page.update()

            def check_thread():
                res = self.api.generate_title("Test", max_len=5)
                refs["check_btn"].disabled = False
                refs["progress"].visible = False
                
                if res is not None:
                    refs["status_text"].value = "Ключ активен"
                    refs["status_text"].color = ft.Colors.GREEN
                else:
                    err = self.api.last_error or "Ошибка сети или ключа"
                    refs["status_text"].value = f"Ошибка: {err}"
                    refs["status_text"].color = ft.Colors.ERROR
                self.page.update()

            threading.Thread(target=check_thread, daemon=True).start()

        def save_settings(key_val: str):
            key = key_val.strip()
            self.db.set_setting("openrouter_api_key", key)
            self.api.set_key(key)
            self._close_dialog(dlg)
            self._update_ai_buttons_state()

        self.dialog_refs = {}
        dlg = dialogs.settings_dialog(current_key, run_test, save_settings, lambda: self._close_dialog(dlg), self.dialog_refs)
        self._open_dialog(dlg)

    def _show_stats(self):
        c = self.db.counts()
        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Статистика"),
            content=ft.Column([ft.Text(f"Заметок: {c['notes']}"), ft.Text(f"Папок: {c['folders']}"), ft.Text(f"Тегов: {c['tags']}")]),
            actions=[ft.TextButton("Ок", on_click=lambda e: self._close_dialog(dlg))],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dlg)

    def _refresh_all(self):
        self._load_folders()
        self._reload_notes()
        self._update_preview()

    def _open_dialog(self, dlg: ft.AlertDialog):
        self.page.open(dlg)

    def _close_dialog(self, dlg: ft.AlertDialog):
        try:
            self.page.close(dlg)
        except Exception:
            dlg.open = False
            self.page.update()

    def _with_loading(self, fn, *args, **kwargs):
        def run():
            try:
                fn(*args, **kwargs)
            except Exception as ex:
                log.exception("Async task failed")
                self._snack(str(ex))
            finally:
                self.loading_overlay.visible = False
                self.page.update()

        self.loading_overlay.visible = True
        self.page.update()
        threading.Thread(target=run, daemon=True).start()

    def _snack(self, msg: str):
        self.page.open(ft.SnackBar(content=ft.Text(msg)))

    def _on_key(self, e: ft.KeyboardEvent):
        if e.ctrl and e.key.lower() == "n":
            self._create_note()
        if e.ctrl and e.key.lower() == "f":
            self.search_field.focus()
            self.page.update()

    def _open_layout_dialog(self):
        left_tf = ft.TextField(label="Левая панель %", value=str(int(self.splitter.left * 100 / 300))) 
        mid_tf = ft.TextField(label="Средняя панель %", value=str(int(self.splitter.mid * 100 / 300)))
        right_tf = ft.TextField(label="Правая панель %", value=str(int(self.splitter.right * 100 / 300)))

        def apply_layout(e):
            try:
                L = int(left_tf.value)
                M = int(mid_tf.value)
                R = int(right_tf.value)
                self.splitter.apply_absolute(int(300 * L/100), int(300 * M/100), 300 - int(300 * L/100) - int(300 * M/100))
                self._save_flex(commit=True)
                self._close_dialog(dlg)
            except Exception as ex:
                self._snack(str(ex))

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Макет панелей"),
            content=ft.Column([left_tf, mid_tf, right_tf], tight=True, width=260),
            actions=[
                ft.TextButton("Отмена", on_click=lambda e: self._close_dialog(dlg)),
                ft.ElevatedButton("Применить", on_click=apply_layout),
            ], actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dlg)