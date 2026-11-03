"""Bounded incremental JSON Lines parser for arbitrary QProcess chunking."""
import json
import math


class Notifications:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data, final=False):
        self.buffer.extend(data)
        if len(self.buffer) > 1024 * 1024:
            raise ValueError("Backend notification exceeds 1 MiB")
        records = []
        while b"\n" in self.buffer:
            line, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            if not line.strip():
                continue
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict) or event.get("event") not in {
                "stage", "progress", "effective", "paused", "resumed", "completed", "error", "cancelled", "model"
            }:
                raise ValueError("Invalid backend notification")
            if event["event"] == "progress":
                for key in ("processed", "total", "fps"):
                    if type(event.get(key)) not in (int, float) or not math.isfinite(event[key]) or event[key] < 0:
                        raise ValueError(f"Invalid progress: {key}")
            records.append(event)
        if final and self.buffer.strip():
            raise ValueError("Truncated backend notification")
        return records
