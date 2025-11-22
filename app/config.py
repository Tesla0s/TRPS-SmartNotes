import logging

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PRIMARY_MODEL = "meituan/longcat-flash-chat:free"
FALLBACK_MODELS = [
    "x-ai/grok-4.1-fast:free",
    "google/gemini-2.0-flash-exp:free",
    "openai/gpt-oss-20b:free"
]

DEFAULT_HEADERS = {
    "HTTP-Referer": "https://smartnotes.local",
    "X-Title": "SmartNotes",
}

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOG_FILE = "smartnotes.log"

def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler()
        ],
    )