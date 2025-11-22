import flet as ft
from app.config import configure_logging
from app.ui.app import SmartNotesApp

def main(page: ft.Page):
    configure_logging()
    SmartNotesApp(page)

if __name__ == "__main__":
    ft.app(target=main)