"""Run the fixed local benchmark sequentially without calling the configured LLM."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from .runner import OfflineBenchmarkRunner


def resolve_chroma_dir(chroma_dir, real_chroma_dir):
    """Resolve an isolated Chroma directory for the offline benchmark.

    Refuse to use the project's real ``chroma_db`` as the benchmark persistence
    directory, so a benchmark run can never mutate production vector data.
    """
    target = os.path.normcase(os.path.abspath(chroma_dir))
    real = os.path.normcase(os.path.abspath(real_chroma_dir))
    if target == real:
        raise ValueError(
            f"拒绝把真实 Chroma 持久化目录用作离线评测目录（{real_chroma_dir}）。"
            "请用 --chroma-dir 指定独立目录，或省略以使用临时目录。"
        )
    return os.path.abspath(chroma_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the local retail analyst benchmark")
    parser.add_argument("--cases", default="evals/cases")
    parser.add_argument("--traces", default="evals/traces")
    parser.add_argument(
        "--chroma-dir",
        default=None,
        help="RAG Chroma 持久化目录；默认使用临时目录（隔离，不写真实 chroma_db）",
    )
    args = parser.parse_args(argv)

    # Set process-local overrides before importing the app module, which loads .env.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_API_KEY"] = ""
    os.environ["LANGCHAIN_API_KEY"] = ""

    from src.agents import graph_workflow

    saved_client = graph_workflow.client
    saved_chroma = graph_workflow.mcp_server.chroma_path

    # Resolve an isolated RAG Chroma directory before mutating any global state.
    own_tmp = None
    if args.chroma_dir:
        try:
            chroma_dir = resolve_chroma_dir(args.chroma_dir, saved_chroma)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        own_tmp = tempfile.TemporaryDirectory()
        chroma_dir = os.path.join(own_tmp.name, "chroma_db")

    graph_workflow.client = None  # deterministic rule routing/template fallback; no LLM request
    graph_workflow.mcp_server.chroma_path = chroma_dir
    runner = OfflineBenchmarkRunner(
        graph_workflow.run_agent, graph_workflow.mcp_server, trace_dir=args.traces
    )
    try:
        files = sorted(Path(args.cases).glob("*.json"))
        if not files:
            parser.error("no benchmark case JSON files found")
        failed = False
        for path in files:
            case = json.loads(path.read_text(encoding="utf-8"))
            report = runner.run_case(case["id"], case["query"])
            trace = report["trace"]
            overall = "fail" if any(
                trace["evaluations"][layer]["status"] == "fail"
                for layer in ("gate", "trajectory")
            ) else "pass"
            failed = failed or overall == "fail"
            print(json.dumps({
                "case_id": case["id"], "run_id": trace["run_id"],
                "business_status": trace["business"]["status"],
                "gate": trace["evaluations"]["gate"]["status"],
                "trajectory": trace["evaluations"]["trajectory"]["status"],
                "trace_path": trace.get("trace_path", ""),
            }, ensure_ascii=False))
        return 1 if failed else 0
    finally:
        graph_workflow.client = saved_client
        graph_workflow.mcp_server.chroma_path = saved_chroma
        if own_tmp is not None:
            own_tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
