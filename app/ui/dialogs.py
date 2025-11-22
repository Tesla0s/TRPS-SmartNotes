import flet as ft
from typing import Callable, List, Dict, Any

def create_folder_dialog(on_create: Callable[[str], None], on_close: Callable) -> ft.AlertDialog:
    tf = ft.TextField(label="Название папки", autofocus=True)
    return ft.AlertDialog(
        modal=True, title=ft.Text("Новая папка"), content=tf,
        actions=[
            ft.TextButton("Отмена", on_click=lambda e: on_close()),
            ft.ElevatedButton("Создать", on_click=lambda e: on_create(tf.value)),
        ], actions_alignment=ft.MainAxisAlignment.END,
    )

def rename_folder_dialog(on_save: Callable[[str], None], on_close: Callable) -> ft.AlertDialog:
    tf = ft.TextField(label="Новое имя папки", autofocus=True)
    return ft.AlertDialog(
        modal=True, title=ft.Text("Переименовать папку"), content=tf,
        actions=[
            ft.TextButton("Отмена", on_click=lambda e: on_close()),
            ft.ElevatedButton("Сохранить", on_click=lambda e: on_save(tf.value)),
        ], actions_alignment=ft.MainAxisAlignment.END,
    )

def delete_folder_dialog(on_delete: Callable, on_close: Callable) -> ft.AlertDialog:
    return ft.AlertDialog(
        modal=True, title=ft.Text("Удалить папку?"),
        content=ft.Text("Заметки сохранятся, но поле папки у них станет пустым."),
        actions=[
            ft.TextButton("Отмена", on_click=lambda e: on_close()),
            ft.ElevatedButton("Удалить", on_click=lambda e: on_delete()),
        ], actions_alignment=ft.MainAxisAlignment.END,
    )

def move_note_dialog(folders: List[Dict], on_move: Callable[[str], None], on_close: Callable) -> ft.AlertDialog:
    options = [ft.dropdown.Option(key="__ALL__", text="(без папки)")]
    for f in folders:
        options.append(ft.dropdown.Option(key=str(f["id"]), text=f["name"]))
    dd = ft.Dropdown(options=options, value="__ALL__", width=350)
    return ft.AlertDialog(
        modal=True, title=ft.Text("Переместить заметку"), content=dd,
        actions=[
            ft.TextButton("Отмена", on_click=lambda e: on_close()),
            ft.ElevatedButton("Переместить", on_click=lambda e: on_move(dd.value)),
        ], actions_alignment=ft.MainAxisAlignment.END,
    )

def settings_dialog(current_key: str, on_test: Callable[[str], None], on_save: Callable[[str], None], on_close: Callable, ui_refs: Dict[str, Any]) -> ft.AlertDialog:
    tf = ft.TextField(
        label="OpenRouter API Key",
        value=current_key or "",
        password=True,
        can_reveal_password=True,
        width=520,
    )
    status_text = ft.Text("", size=12)
    check_btn = ft.ElevatedButton("Проверить ключ")
    progress = ft.ProgressRing(width=20, height=20, visible=False)
    
    ui_refs["status_text"] = status_text
    ui_refs["check_btn"] = check_btn
    ui_refs["progress"] = progress

    check_btn.on_click = lambda e: on_test(tf.value)

    return ft.AlertDialog(
        modal=True, title=ft.Text("Настройки"),
        content=ft.Column(
            [
                tf,
                ft.Row([check_btn, progress, status_text], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], tight=True, width=560,
        ),
        actions=[
            ft.TextButton("Закрыть", on_click=lambda e: on_close()),
            ft.ElevatedButton("Сохранить", on_click=lambda e: on_save(tf.value)),
        ], actions_alignment=ft.MainAxisAlignment.END,
    )