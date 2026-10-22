"""Serial offline wrapper around the existing run_agent callable."""

import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.runnables import RunnableLambda

from . import TRACE_SCHEMA_VERSION
from .callbacks import NodeEventCollector, utc_now
from .gates import run_gates
from .privacy import fingerprint, redact_text, report_excerpt, safe_summary, sanitize
from .trace_writer import write_trace
from .trajectory import validate_trajectory


_SERIAL_BENCHMARK_LOCK = threading.RLock()
_NON_TOOL_TRACE_ROWS = {"intent_recognition", "report_generation"}


def _associate_tool(record, node_names):
    name = record.get("name", "")
    if name == "rag_search":
        return "intent"
    if name in ("query_macro_sqlite", "forecast_timeseries"):
        return "query_macro" if "query_macro" in node_names else ("query_all" if "query_all" in node_names else "")
    if name == "predict_churn_batch":
        return "predict_churn" if "predict_churn" in node_names else ("query_all" if "query_all" in node_names else "")
    return ""


def _tool_records(mcp_server, result, node_events):
    records = []
    source = getattr(mcp_server, "execution_log", []) if mcp_server is not None else []
    if not source and isinstance(result, dict):
        source = result.get("execution_trace", [])
    node_names = [e.get("name") for e in node_events if e.get("scope") == "node"]
    for index, record in enumerate(source or []):
        if record.get("name") in _NON_TOOL_TRACE_ROWS:
            continue
        records.append({
            "call_index": len(records),
            "source_log_index": index,
            "node_name": _associate_tool(record, node_names),
            "name": record.get("name", ""),
            "input": sanitize(record.get("input", {}), text_limit=500),
            "status": record.get("status", "unknown"),
            "duration_ms": record.get("duration_ms"),
            "error": safe_summary(record.get("error", ""), 800),
            "summary": safe_summary(record.get("summary", ""), 800),
            "sql": safe_summary(record.get("sql", ""), 800) if record.get("sql") else "",
            "source": safe_summary(record.get("source", ""), 300) if record.get("source") else "",
        })
    return records


def _state_projection(result):
    if not isinstance(result, dict):
        return {}
    allowed = ("intent", "intent_reason", "generation_status", "fallback_reason")
    state = {key: result.get(key) for key in allowed if key in result}
    state["report_sections"] = sanitize(result.get("report_sections", []), text_limit=1200)
    return sanitize(state, text_limit=3000)


class OfflineBenchmarkRunner:
    """Run benchmark cases serially and persist isolated, privacy-filtered traces."""

    def __init__(self, run_agent, mcp_server=None, trace_dir="evals/traces"):
        self.run_agent = run_agent
        self.mcp_server = mcp_server
        self.trace_dir = Path(trace_dir)

    def run_case(self, case_id, query, image_base64=""):
        run_id = str(uuid.uuid4())
        started_at = utc_now()
        started = time.perf_counter()
        collector = NodeEventCollector()
        result = None
        business_error = None
        evaluation_errors = []
        tool_calls = []
        node_events = []

        # All benchmark callers in this process share the lock. Do not use this for
        # online request collection; the current singleton tool server is shared.
        with _SERIAL_BENCHMARK_LOCK:
            try:
                wrapper = RunnableLambda(
                    lambda payload: self.run_agent(payload["query"], payload["image_base64"])
                )
                result = wrapper.invoke(
                    {"query": query, "image_base64": image_base64 or ""},
                    config={"callbacks": [collector], "run_name": "offline_benchmark_run"},
                )
            except Exception as exc:
                business_error = {
                    "type": type(exc).__name__,
                    "message": safe_summary(str(exc), 1000),
                }
            finally:
                node_events, callback_errors = collector.snapshot()
                evaluation_errors.extend(callback_errors)
                tool_calls = _tool_records(self.mcp_server, result, node_events)

            try:
                gate_result = run_gates(result or {}, tool_calls)
            except Exception as exc:
                gate_result = {"status": "error", "findings": [], "error": safe_summary(str(exc), 800)}
                evaluation_errors.append("gate: " + safe_summary(str(exc), 300))
            try:
                trajectory_result = validate_trajectory(result or {}, node_events, tool_calls)
            except Exception as exc:
                trajectory_result = {"status": "error", "findings": [], "error": safe_summary(str(exc), 800)}
                evaluation_errors.append("trajectory: " + safe_summary(str(exc), 300))

            ended_at = utc_now()
            trace = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "run_id": run_id,
                "case_id": redact_text(str(case_id), 200),
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "business": {
                    "status": (result or {}).get("generation_status", "failed" if business_error else "unknown"),
                    "fallback_reason": safe_summary((result or {}).get("fallback_reason", ""), 500),
                    "error": business_error or {},
                    "final_report_excerpt": report_excerpt((result or {}).get("final_report", ""), 5000),
                    "state_projection": _state_projection(result),
                },
                "input": {
                    "query_sha256": fingerprint(query),
                    "query_length": len(query),
                    "image_base64": "[OMITTED]" if image_base64 else "",
                },
                "node_events": [event for event in node_events if event.get("scope") == "node"],
                "runtime_events": [event for event in node_events if event.get("scope") != "node"],
                "tool_calls": tool_calls,
                "evaluations": {
                    "gate": gate_result,
                    "trajectory": trajectory_result,
                    "judge": {"status": "not_implemented"},
                    "human_calibration": {"status": "not_implemented"},
                    "instrumentation_errors": evaluation_errors,
                },
            }
            try:
                trace["trace_path"] = write_trace(trace, self.trace_dir)
            except Exception as exc:
                # Trace I/O failure is observable but does not replace the business result.
                evaluation_errors.append("trace_write: " + safe_summary(str(exc), 300))
                trace["trace_path"] = ""
                trace["evaluations"]["instrumentation_errors"] = evaluation_errors

        return {"result": result, "trace": trace}


def run_offline_case(case_id, query, image_base64="", trace_dir="evals/traces"):
    """Convenience adapter that lazily binds the existing workflow singleton."""
    from src.agents import graph_workflow

    runner = OfflineBenchmarkRunner(
        graph_workflow.run_agent,
        mcp_server=graph_workflow.mcp_server,
        trace_dir=trace_dir,
    )
    return runner.run_case(case_id, query, image_base64)
