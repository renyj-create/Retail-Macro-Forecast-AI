"""Deterministic report and business/evaluation consistency gates."""

import re


_DISCLOSURE_MARKERS = ("失败", "暂无数据", "未取得", "不可用", "未提供", "未能获取", "降级")
_VERIFICATION_MARKERS = ("已验证", "验证通过", "已确认", "已成功获取", "基于真实数据")


def _finding(name, status, message, details=None):
    return {"name": name, "status": status, "message": message, "details": details or {}}


def _report_text(result):
    return result.get("final_report") or result.get("report") or ""


def _title_positions(report, titles):
    positions = []
    for title in titles:
        positions.append([m.start() for m in re.finditer(re.escape(title), report)])
    return positions


def report_structure_gate(result):
    # Lazy import keeps CLI startup able to turn off remote tracing before loading the app.
    from src.agents.graph_workflow import SECTION_TITLES

    report = _report_text(result)
    if not isinstance(report, str) or not report.strip():
        return _finding("report_structure", "fail", "报告为空")
    positions = _title_positions(report, SECTION_TITLES)
    counts = [len(p) for p in positions]
    missing = [SECTION_TITLES[i] for i, count in enumerate(counts) if count == 0]
    duplicate = [SECTION_TITLES[i] for i, count in enumerate(counts) if count > 1]
    if missing or duplicate:
        return _finding("report_structure", "fail", "六段标题必须各出现一次", {
            "missing": missing, "duplicate": duplicate,
        })
    ordered = [p[0] for p in positions]
    if ordered != sorted(ordered):
        return _finding("report_structure", "fail", "六段标题顺序错误")
    return _finding("report_structure", "pass", "六段标题齐全且顺序正确")


def required_state_gate(result):
    missing = [key for key in ("intent", "generation_status", "final_report") if not result.get(key)]
    if not isinstance(result.get("report_sections"), list):
        missing.append("report_sections")
    if not isinstance(result.get("execution_trace"), list):
        missing.append("execution_trace")
    status = result.get("generation_status")
    reason = result.get("fallback_reason", "")
    if missing:
        return _finding("required_state", "fail", "工作流必要字段缺失", {"missing": missing})
    if status not in ("success", "fallback", "failed"):
        return _finding("required_state", "fail", "未知业务生成状态", {"generation_status": status})
    if status == "fallback" and not reason:
        return _finding("required_state", "fail", "fallback 状态缺少降级原因")
    if status == "success" and reason:
        return _finding("required_state", "warning", "success 状态携带了降级原因")
    return _finding("required_state", "pass", "必要业务状态字段有效", {"generation_status": status})


def tool_failure_disclosure_gate(result, tool_calls):
    report = _report_text(result)
    failed = [item for item in tool_calls if item.get("status") == "failed"]
    if not failed:
        return _finding("tool_failure_disclosure", "pass", "没有失败工具需要检查")
    undisclosed = []
    unsupported_claims = []
    for call in failed:
        name = call.get("name", "")
        # Wording checks are deliberately conservative; semantic truth needs human/Judge review.
        keywords = {
            "query_macro_sqlite": ("社零", "宏观", "同比"),
            "forecast_timeseries": ("预测", "ARIMA", "趋势"),
            "predict_churn_batch": ("流失", "风险分布", "用户"),
            "rag_search": ("知识库", "研报", "RAG"),
        }.get(name, ())
        disclosed = any(marker in report for marker in _DISCLOSURE_MARKERS)
        if not disclosed:
            undisclosed.append(name)
        if keywords and not disclosed and any(word in report for word in keywords) and any(
            marker in report for marker in _VERIFICATION_MARKERS
        ):
            unsupported_claims.append(name)
    if unsupported_claims:
        return _finding("tool_failure_disclosure", "fail", "工具失败时报告仍出现成功验证措辞", {
            "tools": unsupported_claims,
        })
    if undisclosed:
        return _finding("tool_failure_disclosure", "warning", "未能确定报告是否披露工具失败", {
            "tools": undisclosed,
            "note": "关键词规则仅能提示，不能判断语义上的数据真实性",
        })
    return _finding("tool_failure_disclosure", "pass", "报告包含工具失败/数据缺失披露")


def payload_anchor_gate(result):
    """Check presence of a small number of exact structured data anchors; omissions warn."""
    report = _report_text(result)
    checks = []
    macro = result.get("macro_payload") or []
    if macro:
        point = macro[0]
        expected = [str(point.get("date", "")), str(point.get("value", "")), str(point.get("yoy", ""))]
        absent = [value for value in expected if value and value not in report]
        if absent:
            checks.append({"source": "macro_payload.latest", "missing_anchors": absent})
    forecast = result.get("forecast_payload") or {}
    values = forecast.get("forecast_values") or []
    if values:
        anchor = str(values[0])
        # The report may summarize rather than enumerate every horizon, so this is advisory.
        if anchor not in report:
            checks.append({"source": "forecast_payload.first_forecast", "missing_anchors": [anchor]})
    churn = result.get("churn_payload") or {}
    if churn.get("total") is not None:
        anchor = str(churn["total"])
        if anchor not in report:
            checks.append({"source": "churn_payload.total", "missing_anchors": [anchor]})
    if not checks:
        return _finding("payload_report_consistency", "pass", "可检查的结构化数据锚点已出现在报告中")
    return _finding("payload_report_consistency", "warning", "部分结构化数据锚点未在报告原文中找到", {
        "checks": checks,
        "note": "基于格式化字符串的保守检查；不判定数值语义正确性",
    })


def run_gates(result, tool_calls):
    findings = [
        report_structure_gate(result),
        required_state_gate(result),
        payload_anchor_gate(result),
        tool_failure_disclosure_gate(result, tool_calls),
    ]
    statuses = {item["status"] for item in findings}
    overall = "fail" if "fail" in statuses else ("warning" if "warning" in statuses else "pass")
    return {"status": overall, "findings": findings}
