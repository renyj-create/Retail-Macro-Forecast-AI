"""LangGraph callback collection with graph/node/Runnable classification."""

import threading
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .privacy import safe_summary, sanitize


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class NodeEventCollector(BaseCallbackHandler):
    """Collect Runnable events and identify actual LangGraph node wrapper events."""

    run_inline = True
    raise_error = False

    def __init__(self):
        self.events = []
        self.errors = []
        self._starts = {}
        self._lock = threading.Lock()

    @staticmethod
    def _scope(name, metadata, parent_run_id):
        metadata = metadata or {}
        node = metadata.get("langgraph_node")
        if node and name == node:
            return "node"
        if name == "LangGraph" or (
            metadata.get("ls_integration") == "langgraph"
            and not metadata.get("langgraph_step")
            and not node
        ):
            return "graph"
        if parent_run_id is None:
            return "wrapper"
        return "runnable"

    def _record_start(self, serialized, inputs, *, run_id, parent_run_id=None,
                      tags=None, metadata=None, name=None, **kwargs):
        try:
            started = time.perf_counter()
            event = {
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "name": str(name or "unknown"),
                "scope": self._scope(name, metadata, parent_run_id),
                "phase": "started",
                "started_at": utc_now(),
                "duration_ms": None,
                "metadata": sanitize(metadata or {}, text_limit=500),
                "input_summary": safe_summary(inputs),
                "output_summary": "",
                "error_type": "",
                "error": "",
            }
            with self._lock:
                self._starts[str(run_id)] = started
                self.events.append(event)
        except Exception as exc:  # instrumentation must not affect the business run
            self.errors.append("callback_start: " + safe_summary(str(exc), 300))

    def on_chain_start(self, serialized, inputs, **kwargs):
        self._record_start(serialized, inputs, **kwargs)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._finish(run_id, "completed", output=outputs)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, "failed", error=error)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None,
                      tags=None, metadata=None, **kwargs):
        name = (serialized or {}).get("name") or (serialized or {}).get("id") or "tool"
        kwargs.pop("name", None)
        kwargs.pop("inputs", None)
        self._record_start(
            serialized, input_str, run_id=run_id, parent_run_id=parent_run_id,
            tags=tags, metadata=metadata, name=str(name), **kwargs,
        )
        with self._lock:
            event = next((item for item in reversed(self.events) if item["run_id"] == str(run_id)), None)
            if event:
                event["scope"] = "tool"

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._finish(run_id, "completed", output=output)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, "failed", error=error)

    def _finish(self, run_id, phase, output=None, error=None):
        try:
            key = str(run_id)
            ended = time.perf_counter()
            with self._lock:
                event = next((item for item in reversed(self.events) if item["run_id"] == key), None)
                started = self._starts.pop(key, None)
                if event is None:
                    self.errors.append("callback_end_without_start: " + key)
                    return
                event["phase"] = phase
                event["ended_at"] = utc_now()
                event["duration_ms"] = round((ended - started) * 1000, 3) if started else None
                if error is not None:
                    event["error_type"] = type(error).__name__
                    event["error"] = safe_summary(str(error), 1000)
                elif output is not None:
                    event["output_summary"] = safe_summary(output)
        except Exception as exc:
            self.errors.append("callback_finish: " + safe_summary(str(exc), 300))

    def snapshot(self):
        with self._lock:
            return sanitize(self.events), list(self.errors)

    def node_events(self):
        with self._lock:
            return sanitize([item for item in self.events if item["scope"] == "node"])
