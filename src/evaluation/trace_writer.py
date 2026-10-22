"""Atomic local JSON trace writer."""

import json
import os
import tempfile
from pathlib import Path

from .privacy import sanitize


def write_trace(trace, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    trace_id = trace["run_id"]
    target = directory / (trace_id + ".json")
    payload = sanitize(trace, text_limit=10000)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(directory), prefix="." + trace_id + ".",
            suffix=".tmp", delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        return str(target)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
