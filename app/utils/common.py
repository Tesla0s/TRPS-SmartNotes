import threading
import logging
from typing import Callable, Optional

log = logging.getLogger("smartnotes.utils")

class Debouncer:
    def __init__(self, delay_ms: int, fn: Callable):
        self.delay = delay_ms / 1000.0
        self.fn = fn
        self._timer: Optional[threading.Timer] = None

    def call(self, *args, **kwargs):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.delay, self.fn, args=args, kwargs=kwargs)
        self._timer.daemon = True
        self._timer.start()