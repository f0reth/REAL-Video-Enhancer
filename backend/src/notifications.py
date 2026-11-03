"""stdout is reserved for UTF-8 JSON Lines, including native library output."""
import json
import os
import sys
import threading

_stream = None
_lock = threading.Lock()


def initialize():
    global _stream
    sys.stdout.flush()
    _stream = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr


def emit(event, **payload):
    if _stream is not None:
        with _lock:
            _stream.write(json.dumps({"event": event, **payload}, ensure_ascii=False, allow_nan=False) + "\n")
            _stream.flush()
