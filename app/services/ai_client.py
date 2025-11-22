import json
import logging
import time
from typing import List, Optional, Dict, Any
from openai import OpenAI, APIError

from app.config import OPENROUTER_BASE_URL, PRIMARY_MODEL, FALLBACK_MODELS, DEFAULT_HEADERS

log = logging.getLogger("smartnotes.ai")

class OpenRouterClient:
    def __init__(self, api_key: Optional[str]):
        self.api_key = (api_key or "").strip()
        self.client: Optional[OpenAI] = None
        self.model = PRIMARY_MODEL
        self.last_error: Optional[str] = None
        if self.api_key:
            self.client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=self.api_key)

    def available(self) -> bool:
        return bool(self.api_key)

    def set_key(self, key: str):
        self.api_key = (key or "").strip()
        self.last_error = None
        self.client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=self.api_key) if self.api_key else None

    def _chat_once(self, model: str, messages, temperature: float, max_tokens: int) -> Optional[str]:
        assert self.client is not None
        try:
            comp = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_headers=DEFAULT_HEADERS,
            )
            return comp.choices[0].message.content
        except APIError as e:
            self.last_error = f"API Error: {e}"
            log.error(f"API Error: {e}")
            return None
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            log.exception("Chat exception")
            return None

    def _chat(self, messages, temperature: float = 0.2, max_tokens: int = 32768) -> Optional[str]:
        if not self.available():
            self.last_error = "API key is not set"
            log.error("No API key")
            return None

        models = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        delays = [0.0, 1.0, 2.5, 5.0]
        last_err = None

        for _, delay in enumerate(delays):
            if delay:
                time.sleep(delay)
            for m in models:
                out = self._chat_once(m, messages, temperature, max_tokens)
                if out:
                    self.model = m
                    self.last_error = None
                    return out
                last_err = self.last_error
                if last_err:
                    if "No endpoints found" in last_err:
                        log.warning("Data policy may block free models")
                    if "429" in last_err or "rate" in last_err.lower():
                        log.warning("Upstream rate-limited; will retry with backoff")

        if last_err and "No endpoints found" in last_err:
            self.last_error = "Privacy filter blocks free models; enable prompt logging/training in account"
        else:
            self.last_error = last_err or "Unknown error"
        return None

    def improve_text(self, text: str, mode: str) -> Optional[str]:
        style_map = {
            "Fix grammar": "Исправь грамматику и орфографию, сохраняя смысл и стиль автора.",
            "More formal": "Перепиши текст более официально, деловой тон, без жаргона.",
            "Simplify": "Упростить формулировки и сократить сложные обороты, сохраняя смысл.",
        }
        goal = style_map.get(mode, style_map["Fix grammar"])
        sys = "Ты редактор русского текста. Отвечай только отредактированным текстом без комментариев."
        
        return self._chat(
            [{"role": "system", "content": sys},
             {"role": "user", "content": f"{goal}\n\nТекст:\n{text}"}],
            temperature=0.2, max_tokens=32768
        )

    def suggest_tags(self, text: str, max_tags: int = 5) -> List[str]:
        sys = "Ты помощник, который извлекает теги из заметки. Верни JSON-массив коротких тегов на русском языке."
        user = f"Текст заметки:\n{text}\n\nТребования: 3-{max_tags} тегов, только JSON-массив строк без комментариев."
        
        out = self._chat(
            [{"role": "system", "content": sys},
             {"role": "user", "content": user}],
            temperature=0.3, max_tokens=4096
        )
        if not out:
            return []
        try:
            s = out.strip()
            i, j = s.find("["), s.rfind("]")
            if i != -1 and j != -1 and j > i:
                arr = json.loads(s[i:j+1])
                return [str(x).strip() for x in arr if str(x).strip()][:max_tags]
        except Exception as e:
            log.warning("Tag JSON parse failed: %s", e)
        
        raw = [t.strip(" -•,\n\t") for t in out.replace("\n", ",").split(",")]
        return [t for t in raw if t][:max_tags]

    def generate_title(self, text: str, max_len: int = 80) -> Optional[str]:
        sys = "Ты генератор коротких заголовков на русском."
        user = f"Сгенерируй один ёмкий заголовок (до {max_len} символов) без кавычек и точки. Текст:\n{text}"
        return self._chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.6, max_tokens=512
        )

    def summarize(self, text: str, max_sentences: int = 3) -> Optional[str]:
        sys = "Ты пишешь краткие пересказы на русском."
        user = f"Суммаризируй текст в {max_sentences} предложения, без списков и буллетов:\n```\n{text}\n```\n. В конце суммаризации в отдельной строке напиши `---`."
        return self._chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.2, max_tokens=32768
        )