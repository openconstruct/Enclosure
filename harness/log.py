"""Append-only JSONL event log.

Rules:
  - Never mutate a line. Corrections are new lines.
  - Never write a derived score. Scoring is a separate pass over the log.
  - `t` is seconds elapsed since episode start, not wall clock.
"""
import json
import time
from pathlib import Path


class EventLog:
    def __init__(self, path, episode_id):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.episode_id = episode_id
        self.t0 = time.perf_counter()
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, ev, **fields):
        rec = {
            "ep": self.episode_id,
            "t": round(time.perf_counter() - self.t0, 3),
            "ev": ev,
        }
        rec.update(fields)
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()
        return rec

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
