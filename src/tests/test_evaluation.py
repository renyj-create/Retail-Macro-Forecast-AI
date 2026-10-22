"""Offline evaluation infrastructure tests; no tools or external models are called."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

# Avoid loading tracing credentials/configuration from .env during test imports.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["LANGCHAIN_API_KEY"] = ""

from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

import src.agents.graph_workflow as gw
from src.evaluation.callbacks import NodeEventCollector
from src.evaluation.gates import report_structure_gate
from src.evaluation.privacy import sanitize
from src.evaluation.runner import OfflineBenchmarkRunner
from src.evaluation.trace_writer import write_trace
from src.evaluation.trajectory import validate_trajectory
from src.agents.graph_workflow import SECTION_TITLES


class MiniState(TypedDict, total=False):
    value: int
    doubled: int
    tool_value: int


def six_section_report():
    return "\n\n".join(title + "本次为离线测试。" for title in SECTION_TITLES)


def workflow_result(intent, status="success"):
    report = six_section_report()
    return {
        "intent": intent,
        "intent_reason": "规则降级（测试）",
        "generation_status": status,
        "fallback_reason": "测试降级原因" if status == "fallback" else "",
        "final_report": report,
        "report_sections": [{"title": title, "content": "本次为离线测试。"} for title in SECTION_TITLES],
        "execution_trace": [],
        "macro_payload": [],
        "forecast_payload": None,
    }


class TestCallbackCollector(unittest.TestCase):
    def test_node_graph_runnable_and_tool_events(self):
        def add_one(value: int) -> int:
            return value + 1

        tool = StructuredTool.from_function(add_one, name="local_add", description="local test tool")
        nested = RunnableLambda(lambda state: {"doubled": state["value"] * 2})

        def node(state):
            values = nested.invoke({"value": state["value"]})
            return {"doubled": values["doubled"], "tool_value": tool.invoke({"value": state["value"]})}

        graph_builder = StateGraph(MiniState)
        graph_builder.add_node("calc_node", node)
        graph_builder.add_edge(START, "calc_node")
        graph_builder.add_edge("calc_node", END)
        collector = NodeEventCollector()
        result = graph_builder.compile().invoke(
            {"value": 4}, config={"callbacks": [collector], "run_name": "test_graph"}
        )
        self.assertEqual(result["doubled"], 8)
        all_events, errors = collector.snapshot()
        self.assertEqual(errors, [])
        scopes = {(event["name"], event["scope"], event["phase"]) for event in all_events}
        self.assertIn(("calc_node", "node", "completed"), scopes)
        self.assertIn(("RunnableLambda", "runnable", "completed"), scopes)
        self.assertIn(("local_add", "tool", "completed"), scopes)
        node_event = next(event for event in all_events if event["name"] == "calc_node")
        self.assertTrue(node_event["input_summary"])
        self.assertTrue(node_event["output_summary"])
        self.assertGreaterEqual(node_event["duration_ms"], 0)
        self.assertTrue(any(event["scope"] == "graph" for event in all_events))

    def test_node_error_is_recorded_once_as_node_failure(self):
        def fail(state):
            raise ValueError("isolated node failure")

        graph_builder = StateGraph(MiniState)
        graph_builder.add_node("broken_node", fail)
        graph_builder.add_edge(START, "broken_node")
        graph_builder.add_edge("broken_node", END)
        collector = NodeEventCollector()
        with self.assertRaisesRegex(ValueError, "isolated node failure"):
            graph_builder.compile().invoke({"value": 1}, config={"callbacks": [collector]})
        all_events, _ = collector.snapshot()
        node_failures = [e for e in all_events if e["scope"] == "node" and e["phase"] == "failed"]
        graph_failures = [e for e in all_events if e["scope"] == "graph" and e["phase"] == "failed"]
        self.assertEqual(len(node_failures), 1)
        self.assertEqual(node_failures[0]["error_type"], "ValueError")
        self.assertEqual(len(graph_failures), 1)
        trajectory = validate_trajectory(
            {"intent": "宏观分析", "generation_status": "failed"},
            [event for event in all_events if event["scope"] == "node"],
            [],
        )
        node_finding = next(f for f in trajectory["findings"] if f["name"] == "node_failures")
        self.assertEqual(node_finding["details"]["unique_failed_node_count"], 1)


class TestGates(unittest.TestCase):
    def test_missing_duplicate_and_out_of_order_titles_fail(self):
        base = six_section_report()
        self.assertEqual(report_structure_gate({"final_report": base})["status"], "pass")
        missing = base.replace(SECTION_TITLES[2], "", 1)
        self.assertEqual(report_structure_gate({"final_report": missing})["status"], "fail")
        duplicate = base + "\n\n" + SECTION_TITLES[0] + "重复。"
        self.assertEqual(report_structure_gate({"final_report": duplicate})["status"], "fail")
        wrong_order = "\n\n".join(reversed(SECTION_TITLES))
        self.assertEqual(report_structure_gate({"final_report": wrong_order})["status"], "fail")

    def test_recursive_redaction_and_truncation(self):
        value = sanitize({
            "api_key": "sk-test-never-store",
            "image_base64": "long-image-payload",
            "query": "contact a@example.org or 13800138000",
            "nested": [{"user_id": 12345, "ok": "yes"}],
        })
        encoded = json.dumps(value, ensure_ascii=False)
        for secret in ("sk-test-never-store", "long-image-payload", "a@example.org", "13800138000", "12345"):
            self.assertNotIn(secret, encoded)

    def test_truncation_limits_long_text_and_lists(self):
        out = sanitize({"a": "x" * 10000})
        self.assertTrue(out["a"].endswith("…[TRUNCATED]"))
        self.assertEqual(len(out["a"]), 3000 + len("…[TRUNCATED]"))
        out2 = sanitize({"lst": list(range(100))})
        self.assertEqual(len(out2["lst"]), 41)
        self.assertEqual(out2["lst"][-1], "[TRUNCATED_ITEMS]")


class TestOfflineRunner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original_client = gw.client
        gw.client = None
        self.addCleanup(setattr, gw, "client", self.original_client)

    def _record(self, name, status="success", error=""):
        gw.mcp_server._record(
            name, status, name + " summary", input_params={"query": "offline benchmark"},
            error=error, duration_ms=0.2,
        )

    def _patch_graph(self, intent, status="success"):
        def analyze(state):
            self._record("rag_search")
            return {
                "intent": intent, "intent_reason": "规则降级（测试）",
                "intent_duration_ms": 0.1, "rag_result": "脱敏测试知识片段",
            }

        def macro(state):
            self._record("query_macro_sqlite")
            self._record("forecast_timeseries")
            return {"macro_result": "测试宏观数据", "forecast_result": "测试预测数据"}

        def churn(state):
            self._record("predict_churn_batch")
            return {"churn_result": "测试流失数据"}

        def all_tools(state):
            self._record("query_macro_sqlite")
            self._record("forecast_timeseries")
            self._record("predict_churn_batch")
            return {"macro_result": "测试宏观数据", "forecast_result": "测试预测", "churn_result": "测试流失"}

        def report(state):
            result = workflow_result(intent, status=status)
            result["execution_trace"] = list(gw.mcp_server.execution_log)
            return result

        for name, function in (
            ("analyze_intent_and_image", analyze), ("query_macro", macro),
            ("predict_churn", churn), ("query_all", all_tools), ("generate_report", report),
        ):
            patcher = patch.object(gw, name, function)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, intent, status="success", run_id="case"):
        self._patch_graph(intent, status)
        runner = OfflineBenchmarkRunner(gw.run_agent, gw.mcp_server, Path(self.temp.name) / "traces")
        return runner.run_case(run_id, "offline benchmark query", image_base64="encoded image must not persist")

    def test_actual_workflow_callback_boundary_and_three_paths(self):
        expected = {
            "宏观分析": (("intent", "query_macro", "report"), ["rag_search", "query_macro_sqlite", "forecast_timeseries"]),
            "流失预测": (("intent", "predict_churn", "report"), ["rag_search", "predict_churn_batch"]),
            "综合分析": (("intent", "query_all", "report"), ["rag_search", "query_macro_sqlite", "forecast_timeseries", "predict_churn_batch"]),
        }
        for intent, (nodes, tools) in expected.items():
            # Reinstall per-case patches because each subtest builds a fresh graph.
            with self.subTest(intent=intent):
                output = self._run(intent, run_id=intent)
                trace = output["trace"]
                self.assertEqual(tuple(e["name"] for e in trace["node_events"]), nodes)
                self.assertEqual([c["name"] for c in trace["tool_calls"]], tools)
                self.assertEqual(trace["evaluations"]["trajectory"]["status"], "pass")
                encoded = Path(trace["trace_path"]).read_text(encoding="utf-8")
                self.assertNotIn("encoded image must not persist", encoded)
                self.assertNotIn("offline benchmark query", encoded)

    def test_business_fallback_is_separate_from_evaluation_status(self):
        output = self._run("流失预测", status="fallback", run_id="fallback")
        trace = output["trace"]
        self.assertEqual(trace["business"]["status"], "fallback")
        self.assertEqual(trace["evaluations"]["gate"]["status"], "pass")
        self.assertEqual(trace["evaluations"]["trajectory"]["status"], "pass")

    def test_gate_and_trace_writer_errors_do_not_change_business_result(self):
        self._patch_graph("流失预测")
        runner = OfflineBenchmarkRunner(gw.run_agent, gw.mcp_server, Path(self.temp.name) / "traces")
        with patch("src.evaluation.runner.run_gates", side_effect=RuntimeError("gate broke")), \
             patch("src.evaluation.runner.write_trace", side_effect=OSError("disk unavailable")):
            output = runner.run_case("safe-errors", "offline benchmark query")
        self.assertEqual(output["result"]["generation_status"], "success")
        self.assertEqual(output["trace"]["evaluations"]["gate"]["status"], "error")
        self.assertEqual(output["trace"]["trace_path"], "")
        self.assertTrue(any("trace_write" in e for e in output["trace"]["evaluations"]["instrumentation_errors"]))

    def test_serial_runs_have_unique_isolated_trace_files(self):
        paths = []
        run_ids = []
        for index in range(3):
            output = self._run("流失预测", run_id="serial-" + str(index))
            paths.append(output["trace"]["trace_path"])
            run_ids.append(output["trace"]["run_id"])
        self.assertEqual(len(set(run_ids)), 3)
        self.assertEqual(len(set(paths)), 3)
        payloads = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
        self.assertEqual({payload["case_id"] for payload in payloads}, {"serial-0", "serial-1", "serial-2"})
        self.assertTrue(all(payload["tool_calls"][0]["node_name"] == "intent" for payload in payloads))

    def test_state_projection_allowlist(self):
        output = self._run("流失预测", run_id="allowlist")
        proj = output["trace"]["business"]["state_projection"]
        self.assertTrue(set(proj.keys()) <= {"intent", "intent_reason", "generation_status", "fallback_reason", "report_sections"})
        for forbidden in ("final_report", "query", "image_base64", "execution_trace", "macro_payload"):
            self.assertNotIn(forbidden, proj)

    def test_tool_call_record_allowlist(self):
        output = self._run("流失预测", run_id="tool-allowlist")
        allowed = {"call_index", "source_log_index", "node_name", "name", "input", "status", "duration_ms", "error", "summary", "sql", "source"}
        self.assertTrue(output["trace"]["tool_calls"])
        for call in output["trace"]["tool_calls"]:
            self.assertTrue(set(call.keys()) <= allowed)

    def test_write_trace_leaves_no_tmp_files(self):
        trace_dir = Path(self.temp.name) / "traces-atomic"
        path = write_trace({"run_id": "atomic-test", "case_id": "x", "note": "hello"}, trace_dir)
        self.assertTrue(Path(path).exists())
        leftovers = [p for p in trace_dir.iterdir() if p.suffix == ".tmp" or p.name.startswith(".atomic-test.")]
        self.assertEqual(leftovers, [])

    def test_write_trace_cleans_tmp_on_failure(self):
        trace_dir = Path(self.temp.name) / "traces-cleanup"
        with patch("src.evaluation.trace_writer.json.dump", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                write_trace({"run_id": "cleanup-test", "case_id": "x"}, trace_dir)
        self.assertEqual(list(trace_dir.iterdir()), [])

    def test_concurrent_runs_have_isolated_traces(self):
        from concurrent.futures import ThreadPoolExecutor
        self._patch_graph("流失预测")
        runner = OfflineBenchmarkRunner(gw.run_agent, gw.mcp_server, Path(self.temp.name) / "traces-conc")
        run_ids = [f"conc-{i}" for i in range(6)]

        def one(rid):
            return runner.run_case(rid, "offline benchmark query")["trace"]

        with ThreadPoolExecutor(max_workers=4) as ex:
            traces = list(ex.map(one, run_ids))
        self.assertEqual(len({t["run_id"] for t in traces}), 6)
        self.assertEqual(len({t["trace_path"] for t in traces}), 6)
        payloads = [json.loads(Path(t["trace_path"]).read_text(encoding="utf-8")) for t in traces]
        self.assertEqual({p["case_id"] for p in payloads}, set(run_ids))
        self.assertTrue(all(p["tool_calls"] and p["tool_calls"][0]["node_name"] == "intent" for p in payloads))


class TestEndToEndOffline(unittest.TestCase):
    """真实工作流 + 真实本地工具，client=None（不调用真实模型 API）。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original_client = gw.client
        gw.client = None
        self.addCleanup(setattr, gw, "client", self.original_client)
        self.original_chroma = gw.mcp_server.chroma_path
        gw.mcp_server.chroma_path = str(Path(self.temp.name) / "chroma_db")
        self.addCleanup(setattr, gw.mcp_server, "chroma_path", self.original_chroma)

    def test_real_workflow_real_tools_offline(self):
        runner = OfflineBenchmarkRunner(gw.run_agent, gw.mcp_server, Path(self.temp.name) / "traces")
        cases = {
            "macro-smoke": "分析最近社零数据走势并说明预测情况",
            "churn-smoke": "分析用户流失预测结果和风险分布",
            "comprehensive-smoke": "结合宏观零售数据和用户流失情况给出运营建议",
        }
        for case_id, query in cases.items():
            with self.subTest(case_id=case_id):
                output = runner.run_case(case_id, query)
                trace = output["trace"]
                self.assertTrue(Path(trace["trace_path"]).exists())
                self.assertEqual(trace["business"]["status"], "fallback")
                self.assertEqual(trace["evaluations"]["gate"]["status"], "pass")
                self.assertEqual(trace["evaluations"]["trajectory"]["status"], "pass")
                encoded = Path(trace["trace_path"]).read_text(encoding="utf-8")
                self.assertNotIn(query, encoded)


class TestCliIsolation(unittest.TestCase):
    def setUp(self):
        self.saved_client = gw.client
        self.saved_chroma = gw.mcp_server.chroma_path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self._tmp_cases = str(Path(self.temp.name) / "cases")
        self._tmp_traces = str(Path(self.temp.name) / "traces")
        self._tmp_chroma = str(Path(self.temp.name) / "chroma")
        Path(self._tmp_cases).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        gw.client = self.saved_client
        gw.mcp_server.chroma_path = self.saved_chroma

    def test_resolve_chroma_dir_returns_isolated_absolute_path(self):
        from src.evaluation.cli import resolve_chroma_dir
        out = resolve_chroma_dir("evals/chroma", self.saved_chroma)
        self.assertTrue(os.path.isabs(out))
        self.assertNotEqual(
            os.path.normcase(os.path.normpath(out)),
            os.path.normcase(os.path.normpath(os.path.abspath(self.saved_chroma))),
        )

    def test_resolve_chroma_dir_refuses_real_chroma(self):
        from src.evaluation.cli import resolve_chroma_dir
        with self.assertRaises(ValueError):
            resolve_chroma_dir(self.saved_chroma, self.saved_chroma)

    def _fake_runner(self, captured):
        class FakeRunner:
            def __init__(self, run_agent, mcp_server, trace_dir=None):
                captured["chroma_during"] = mcp_server.chroma_path

            def run_case(self, case_id, query, image_base64=""):
                return {
                    "result": {"generation_status": "success"},
                    "trace": {
                        "run_id": "fake-run",
                        "business": {"status": "success"},
                        "evaluations": {"gate": {"status": "pass"}, "trajectory": {"status": "pass"}},
                        "trace_path": "",
                    },
                }
        return FakeRunner

    def test_cli_default_chroma_is_isolated_and_restored(self):
        from src.evaluation import cli
        (Path(self._tmp_cases) / "one.json").write_text(
            json.dumps({"id": "one", "query": "分析最近社零数据走势"}), encoding="utf-8"
        )
        captured = {}
        with patch.object(cli, "OfflineBenchmarkRunner", self._fake_runner(captured)):
            rc = cli.main(["--cases", self._tmp_cases, "--traces", self._tmp_traces])
        self.assertEqual(rc, 0)
        self.assertNotEqual(
            os.path.normcase(os.path.normpath(captured["chroma_during"])),
            os.path.normcase(os.path.normpath(os.path.abspath(self.saved_chroma))),
        )
        self.assertEqual(gw.mcp_server.chroma_path, self.saved_chroma)
        self.assertEqual(gw.client, self.saved_client)

    def test_cli_chroma_dir_override_is_honored(self):
        from src.evaluation import cli
        (Path(self._tmp_cases) / "one.json").write_text(
            json.dumps({"id": "one", "query": "分析最近社零数据走势"}), encoding="utf-8"
        )
        override = os.path.join(self._tmp_chroma, "my_chroma")
        captured = {}
        with patch.object(cli, "OfflineBenchmarkRunner", self._fake_runner(captured)):
            rc = cli.main(["--cases", self._tmp_cases, "--traces", self._tmp_traces, "--chroma-dir", override])
        self.assertEqual(rc, 0)
        self.assertEqual(
            os.path.normcase(os.path.normpath(captured["chroma_during"])),
            os.path.normcase(os.path.normpath(os.path.abspath(override))),
        )
        self.assertEqual(gw.mcp_server.chroma_path, self.saved_chroma)

    def test_cli_refuses_when_chroma_dir_is_real(self):
        from src.evaluation import cli
        with self.assertRaises(SystemExit):
            cli.main(["--cases", "does-not-matter", "--chroma-dir", self.saved_chroma])
        self.assertEqual(gw.mcp_server.chroma_path, self.saved_chroma)
        self.assertEqual(gw.client, self.saved_client)


if __name__ == "__main__":
    unittest.main()
