"""Validate observed LangGraph nodes and existing MCPToolServer execution records."""


_PATHS = {
    "宏观分析": ("intent", "query_macro", "report"),
    "流失预测": ("intent", "predict_churn", "report"),
    "综合分析": ("intent", "query_all", "report"),
}
_TOOLS = {
    "宏观分析": ("rag_search", "query_macro_sqlite", "forecast_timeseries"),
    "流失预测": ("rag_search", "predict_churn_batch"),
    "综合分析": ("rag_search", "query_macro_sqlite", "forecast_timeseries", "predict_churn_batch"),
}
_KNOWN_TOOLS = set(sum((list(value) for value in _TOOLS.values()), []))


def _finding(name, status, message, details=None):
    return {"name": name, "status": status, "message": message, "details": details or {}}


def validate_trajectory(result, node_events, tool_calls):
    intent = result.get("intent")
    expected_nodes = _PATHS.get(intent)
    actual_nodes = [event.get("name") for event in node_events if event.get("scope") == "node"]
    actual_tools = [call.get("name") for call in tool_calls]
    problems = []
    if expected_nodes is None:
        problems.append({"type": "unknown_intent", "intent": intent})
    else:
        if actual_nodes != list(expected_nodes):
            problems.append({"type": "node_path", "expected": list(expected_nodes), "actual": actual_nodes})
        if len(actual_nodes) != len(set(actual_nodes)):
            problems.append({"type": "duplicate_node_events"})
        expected_tools = list(_TOOLS[intent])
        if actual_tools != expected_tools:
            problems.append({"type": "tool_sequence", "expected": expected_tools, "actual": actual_tools})
        unexpected = [name for name in actual_tools if name not in _KNOWN_TOOLS]
        if unexpected:
            problems.append({"type": "unexpected_tools", "tools": unexpected})

    failed_nodes = {}
    for event in node_events:
        if event.get("phase") == "failed" and event.get("scope") == "node":
            key = event.get("run_id") or event.get("name")
            failed_nodes[key] = {
                "name": event.get("name"),
                "error_type": event.get("error_type", ""),
                "run_id": event.get("run_id"),
            }
    tool_errors = [
        {"name": call.get("name"), "status": call.get("status"), "error": call.get("error", "")}
        for call in tool_calls if call.get("status") in ("failed", "not_configured")
    ]
    path_status = "fail" if problems else "pass"
    status_consistency = "warning" if tool_errors else "pass"
    findings = [
        _finding("node_path", path_status, "节点路径符合预期" if not problems else "节点/工具路径与意图规则不一致", {
            "problems": problems,
        }),
        _finding("node_failures", "pass", "节点异常按节点 run_id 去重", {
            "unique_failed_node_count": len(failed_nodes),
            "failures": list(failed_nodes.values()),
        }),
        _finding("tool_statuses", status_consistency,
                 "存在失败或未配置工具，需结合业务降级状态审查" if tool_errors else "工具状态正常",
                 {"tool_errors": tool_errors, "business_generation_status": result.get("generation_status")}),
    ]
    statuses = {item["status"] for item in findings}
    overall = "fail" if "fail" in statuses else ("warning" if "warning" in statuses else "pass")
    return {"status": overall, "findings": findings}
