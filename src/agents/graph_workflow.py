# src/agents/graph_workflow.py

import json
import os
import re
import sys
import time
from typing import TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from src.agents.tools import MCPToolServer


# 将项目根目录加入 Python 搜索路径
BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)


# 加载项目根目录下的 .env 文件
load_dotenv(os.path.join(BASE_DIR, ".env"))


# 大模型配置（DeepSeek，OpenAI 兼容接口）
API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


# LangSmith 追踪配置
# 这些变量已经配置在 .env 中时，不需要在代码中重复填写密钥
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT = os.getenv(
    "LANGSMITH_PROJECT",
    "retail-macro-forecast-ai",
)


# 报告六段式结构（标题必须与解析器严格一致）
SECTION_TITLES = [
    "【核心结论】",
    "【数据依据】",
    "【趋势与预测分析】",
    "【异常与风险】",
    "【建议的下一步分析】",
    "【结果限制与不确定性】",
]


# 初始化大模型客户端
# wrap_openai 用于将 OpenAI 兼容接口的模型调用接入 LangSmith 追踪
client = None

if API_KEY:
    try:
        raw_client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
            timeout=30.0,
        )

        if LANGSMITH_TRACING:
            client = wrap_openai(raw_client)
            print("[Agent] DeepSeek 客户端已启用 LangSmith 追踪")
        else:
            client = raw_client
            print("[Agent] LangSmith 追踪未启用")

    except Exception as e:
        print(f"[Agent] 初始化大模型客户端失败: {e}")
else:
    print("[Agent] 未配置 DEEPSEEK_API_KEY，将使用原有兜底逻辑")


# 初始化工具服务
mcp_server = MCPToolServer()



class AgentState(TypedDict, total=False):
    query: str
    image_base64: str
    intent: str
    intent_reason: str
    intent_duration_ms: float
    macro_result: str
    churn_result: str
    forecast_result: str
    rag_result: str
    kb_fragments: str
    final_report: str
    report_sections: list
    execution_trace: list
    macro_payload: list
    forecast_payload: dict
    churn_payload: dict
    generation_status: str
    fallback_reason: str
    suggestions: list
    fact_check: dict


def _llm_chat(system_prompt: str, user_content: str, temperature: float = 0.2,
              timeout: float = 30.0):
    """统一的大模型调用封装，异常时抛出以便上层降级。"""
    if client is None:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，大模型不可用")
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
        timeout=timeout,
    )
    return response.choices[0].message.content.strip()


# 规则兜底意图识别的关键词（大模型不可用时的降级路径）
_MACRO_KEYWORDS = ("宏观", "社零", "零售", "消费", "走势", "趋势")
_CHURN_KEYWORDS = ("流失", "留存", "召回")


def _rule_based_intent(query: str) -> str:
    """基于关键词的规则意图识别（确定性）。"""
    has_macro = any(k in query for k in _MACRO_KEYWORDS)
    has_churn = any(k in query for k in _CHURN_KEYWORDS)
    if has_macro and not has_churn:
        return "宏观分析"
    if has_churn and not has_macro:
        return "流失预测"
    return "综合分析"


def _map_llm_intent(raw: str) -> str:
    """把大模型原始输出归一化为三种意图之一。"""
    if "宏观" in raw and "流失" not in raw:
        return "宏观分析"
    if "流失" in raw and "宏观" not in raw:
        return "流失预测"
    return "综合分析"


def _reconcile_intent(query: str, llm_intent):
    """
    一致性修正：单域问题（仅含宏观 / 仅含流失关键词）采用确定性规则结果，
    避免大模型把宏观或流失单域误判为「综合分析」而错误编排无关工具；
    双域或都不含关键词时信任大模型判断。
    """
    rule_intent = _rule_based_intent(query)
    if rule_intent != "综合分析":
        return rule_intent
    return llm_intent if llm_intent else "综合分析"


def analyze_intent_and_image(state: AgentState):
    query = state["query"]
    image_base64 = state.get("image_base64", "")

    started = time.perf_counter()
    rag_result, kb_fragments = mcp_server.rag_search(query)

    # 图片处理：当前后端未接入真实多模态模型，如实标记为「未接入」，不伪造识图结果
    image_note = ""
    if image_base64:
        image_note = "（用户上传了图片，当前多模态识图能力未接入，本次分析仅基于文本问题与数据工具。）"

    system_prompt = (
        "你是一个零售数据分析助手。请判断用户意图，只输出以下三种之一："
        "「宏观分析」「流失预测」「综合分析」。不要输出其他任何内容。"
    )
    user_content = f"用户提问：{query}"
    if image_note:
        user_content += "\n" + image_note

    llm_intent = None
    try:
        raw_intent = _llm_chat(system_prompt, user_content, temperature=0.1, timeout=20.0)
        llm_intent = _map_llm_intent(raw_intent)
    except Exception as e:
        print(f"  [Agent] 意图识别 API 调用失败，降级为规则匹配。错误: {e}")

    # 确定性一致性修正：单域问题不被大模型误判为「综合分析」
    rule_intent = _rule_based_intent(query)
    if rule_intent != "综合分析":
        intent = rule_intent
        if llm_intent == rule_intent:
            intent_reason = "大模型识别"
        elif llm_intent is None:
            intent_reason = "规则降级（大模型不可用）"
        else:
            intent_reason = "规则校正"
    else:
        intent = llm_intent if llm_intent else "综合分析"
        intent_reason = "大模型识别" if llm_intent else "规则降级（大模型不可用）"

    duration_ms = (time.perf_counter() - started) * 1000
    print(f"[Agent] 意图识别结果: {intent}（{intent_reason}）")

    return {
        "intent": intent,
        "intent_reason": intent_reason,
        "intent_duration_ms": round(duration_ms, 1),
        "rag_result": rag_result,
        "kb_fragments": kb_fragments,
    }


def route_after_intent(state: AgentState):
    if state["intent"] == "宏观分析":
        return "query_macro"
    elif state["intent"] == "流失预测":
        return "predict_churn"
    else:
        return "query_all"


def query_macro(state: AgentState):
    """宏观分析：真实 SQL 查询 + ARIMA 时序预测 + 异常检测。"""
    macro_result, macro_payload = mcp_server.query_macro_sqlite(limit=12)
    forecast_result, forecast_payload = mcp_server.forecast_timeseries()
    return {
        "macro_result": macro_result,
        "forecast_result": forecast_result,
        "macro_payload": macro_payload,
        "forecast_payload": forecast_payload,
    }


def predict_churn(state: AgentState):
    """流失预测：真实 LightGBM 批量推理。"""
    churn_result, churn_payload = mcp_server.predict_churn_batch(top_n=20)
    return {"churn_result": churn_result, "churn_payload": churn_payload}


def query_all(state: AgentState):
    """综合分析：宏观 + 时序预测 + 流失批量推理组合。"""
    macro_result, macro_payload = mcp_server.query_macro_sqlite(limit=12)
    forecast_result, forecast_payload = mcp_server.forecast_timeseries()
    churn_result, churn_payload = mcp_server.predict_churn_batch(top_n=20)
    return {
        "macro_result": macro_result,
        "forecast_result": forecast_result,
        "churn_result": churn_result,
        "macro_payload": macro_payload,
        "forecast_payload": forecast_payload,
        "churn_payload": churn_payload,
    }


def build_fallback_report(macro_result: str, churn_result: str,
                          forecast_result: str, rag_result: str) -> str:
    """大模型不可用时的兜底报告，保证六段结构完整、内容来自真实工具结果。"""
    data_lines = []
    if macro_result:
        data_lines.append("宏观社零数据（SQL 查询）：\n" + macro_result)
    if forecast_result:
        data_lines.append("时序预测（ARIMA）：\n" + forecast_result)
    if churn_result:
        data_lines.append("用户流失预测（LightGBM）：\n" + churn_result)
    if rag_result:
        data_lines.append("知识库检索（RAG）：\n" + rag_result)
    data_part = "\n\n".join(data_lines) if data_lines else "（本次未取得任何工具数据）"

    rag_used = rag_result if rag_result else "（本次未检索到知识库内容）"

    return (
        "【核心结论】\n"
        "本次分析由模板兜底生成（大模型服务不可用），以下结论直接汇总自真实工具执行结果，"
        "未做任何模型推断。\n\n"
        "【数据依据】\n" + data_part + "\n\n"
        "【趋势与预测分析】\n" + (forecast_result if forecast_result else "暂无预测数据") + "\n\n"
        "【异常与风险】\n"
        "请依据上方时序预测中的异常月份与流失风险分布判断；若无异常数据则显示暂无数据。\n\n"
        "【建议的下一步分析】\n"
        "建议优先关注高流失风险用户并复核宏观消费增速变化对复购的影响。\n\n"
        "【结果限制与不确定性】\n"
        "本报告为模板兜底结果，未经过大模型语义归纳；微观用户数据为模拟数据，预测结果仅供演示。"
    )


def classify_llm_error(e: Exception) -> str:
    """将大模型调用异常归类为可读的中文原因，用于回传前端展示。"""
    msg = str(e).lower()
    if any(k in msg for k in ("未配置", "deepseek_api_key", "api key not")):
        return "未配置 API Key"
    if any(k in msg for k in ("401", "unauthorized", "authentication", "api key")):
        return "API Key 无效或鉴权失败"
    if any(k in msg for k in ("timeout", "timed out")):
        return "请求超时"
    if any(k in msg for k in ("429", "rate limit", "too many requests")):
        return "触发限流（Rate Limit）"
    if any(k in msg for k in ("connection", "network", "refused", "unreachable")):
        return "网络连接失败"
    return f"未知异常：{str(e)[:120]}"


def parse_report_sections(report: str):
    """把报告文本解析为有序六段式 list[dict]，忽略标题前的说明文字。"""
    sections = []
    current_title = None
    current_lines = []

    def _flush():
        nonlocal current_title, current_lines
        if current_title is not None:
            sections.append({
                "title": current_title,
                "content": "\n".join(current_lines).strip(),
            })
        current_lines = []

    for line in report.splitlines():
        stripped = line.strip()
        matched = None
        for t in SECTION_TITLES:
            if stripped.startswith(t):
                matched = t
                break
        if matched:
            _flush()
            current_title = matched
            remainder = stripped[len(matched):].strip()
            if remainder:
                current_lines.append(remainder)
        else:
            current_lines.append(line)
    _flush()
    return sections


_SUGGESTION_KEYS = ("title", "description", "rationale", "evidence", "category", "priority")
_PRIORITY_VALUES = {"高", "中", "普通"}
_MAX_SUGGESTIONS = 5
_SUGGESTIONS_FENCE = re.compile(r"```(?:suggestions|json)\s*\n(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def _normalize_suggestions(raw):
    """把大模型返回的原始建议数据规范化为统一 dict 列表；异常数据安全降级为空。"""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        s = {k: "" for k in _SUGGESTION_KEYS}
        for k in _SUGGESTION_KEYS:
            v = item.get(k)
            s[k] = v.strip() if isinstance(v, str) else ("" if v is None else str(v).strip())
        if not s["title"] and not s["description"]:
            continue  # 丢弃空建议
        if s["priority"] not in _PRIORITY_VALUES:
            s["priority"] = "普通"
        out.append(s)
        if len(out) >= _MAX_SUGGESTIONS:
            break
    return out


def _extract_suggestions(text: str):
    """从报告文本中剥离 ```suggestions JSON 块，返回 (clean_text, suggestions)。"""
    m = _SUGGESTIONS_FENCE.search(text or "")
    if not m:
        return (text or ""), []
    clean = (text[:m.start()] + text[m.end():]).strip()
    try:
        data = json.loads(m.group(1).strip())
    except Exception:
        return clean, []
    return clean, _normalize_suggestions(data)


def _collect_fact_anchors(macro_payload, forecast_payload, churn_payload):
    """从结构化 payload 生成少量高置信度关键数字锚点（字符串，与工具文本一致）。"""
    anchors = []
    if macro_payload and isinstance(macro_payload[0], dict):
        v = macro_payload[0].get("value")
        if v is not None:
            anchors.append(str(v))
    if forecast_payload and isinstance(forecast_payload, dict) and forecast_payload.get("forecast_values"):
        anchors.append(str(forecast_payload["forecast_values"][0]))
    if churn_payload and isinstance(churn_payload, dict) and churn_payload.get("total") is not None:
        anchors.append(str(churn_payload["total"]))
    return anchors


def _check_fact_anchors(report_text, anchors):
    """关键数字覆盖检查：全部命中 ok；部分/全部缺失 warning；无锚点 skipped。

    注意：这是覆盖检查，不是事实校验，不能发现报告中的其他错误数字。
    """
    if not anchors:
        return {"status": "skipped", "checked": 0, "found": 0, "missing": [],
                "reason": "无可检查的关键数字锚点"}
    report_text = report_text or ""
    missing = [a for a in anchors if a not in report_text]
    found = [a for a in anchors if a in report_text]
    status = "ok" if not missing else "warning"
    return {"status": status, "checked": len(anchors), "found": len(found), "missing": missing}


_CITY_TIERS = ("一线", "二线", "三线")
# 报告常见写法「用户10407（二线，32岁）」：按稳定用户 ID 定位，捕获城市等级与年龄
_USER_FIELDS_RE = re.compile(r"用户(\d+)\s*[（(]\s*([一二三]线)\s*[，,、]\s*(\d+)\s*岁")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_FIELD_LABELS = {"city_tier": "城市等级", "age": "年龄", "churn_prob": "流失概率"}


def _collect_churn_user_facts(churn_payload, limit=3):
    """从结构化 churn payload 提取用户级字段事实（稳定 user_id → 城市等级/年龄/流失概率）。

    事实来源：churn_inference.predict_batch 返回的 top_risk_users
    （含 user_id / city_tier / age / churn_prob，均为真实模型推理结果）。
    """
    facts = []
    if not isinstance(churn_payload, dict):
        return facts
    users = churn_payload.get("top_risk_users") or []
    for u in users[:limit]:
        if not isinstance(u, dict):
            continue
        uid = u.get("user_id")
        if uid is None:
            continue
        prob = u.get("churn_prob")
        facts.append({
            "user_id": str(int(uid)),
            "city_tier": u.get("city_tier"),
            "age": int(u["age"]) if u.get("age") is not None else None,
            "churn_prob_pct": f"{round(float(prob) * 100, 1)}%" if prob is not None else None,
        })
    return facts


def _check_churn_user_fields(report_text, facts):
    """用户级字段覆盖核对（非完整事实核验）。

    对报告中「用户{id}（城市等级，年龄岁）」形式的提及，按稳定用户 ID 定位并逐字段
    与工具结果核对；流失概率在该用户之后的短窗口内核对。只报告与工具结果明确不一致的
    字段，不校验 LLM 自行发挥、且工具结果无权威值的内容。
    """
    report_text = report_text or ""
    if not facts:
        return {"status": "skipped", "checked": 0, "mismatches": [],
                "reason": "无可检查的用户级字段锚点"}
    by_uid = {f["user_id"]: f for f in facts}
    mismatches = []
    checked = 0
    for m in _USER_FIELDS_RE.finditer(report_text):
        uid = m.group(1)
        fact = by_uid.get(uid)
        if fact is None:
            continue  # 报告提到的用户不在权威事实中，超出本次核对范围
        checked += 1
        tier, age = m.group(2), m.group(3)
        if fact["city_tier"] in _CITY_TIERS and tier != fact["city_tier"]:
            mismatches.append({"user_id": uid, "field": "city_tier",
                               "expected": fact["city_tier"], "found": tier})
        if fact["age"] is not None and int(age) != fact["age"]:
            mismatches.append({"user_id": uid, "field": "age",
                               "expected": str(fact["age"]), "found": age})
    # 流失概率：报告中提到的用户，在其后短窗口内核对首个百分比值
    for uid, fact in by_uid.items():
        idx = report_text.find(uid)
        if idx < 0:
            continue
        pm = _PCT_RE.search(report_text[idx:idx + 80])
        if pm and fact["churn_prob_pct"] is not None:
            found = f"{float(pm.group(1)):.1f}%"
            if found != fact["churn_prob_pct"]:
                mismatches.append({"user_id": uid, "field": "churn_prob",
                                   "expected": fact["churn_prob_pct"], "found": found})
    status = "ok" if not mismatches else "warning"
    return {"status": status, "checked": checked, "mismatches": mismatches}


def _append_user_field_note(report_text, mismatches):
    """把用户级字段不一致以受控说明追加到报告末尾，明确权威值；不擅自改写 LLM 原文。"""
    lines = []
    for m in mismatches:
        lines.append(
            f"- 用户{m['user_id']} {_FIELD_LABELS.get(m['field'], m['field'])}："
            f"报告写「{m['found']}」，工具结果为「{m['expected']}」"
        )
    note = (
        "\n\n字段核对提示（与工具结果对比，非完整事实核验）：\n"
        + "\n".join(lines)
        + "\n以上字段请以工具输出为准。"
    )
    return report_text.rstrip() + note


def generate_report(state: AgentState):
    print("[Agent] 正在生成结构化诊断报告...")
    query = state.get("query", "")
    macro_result = state.get("macro_result", "")
    churn_result = state.get("churn_result", "")
    forecast_result = state.get("forecast_result", "")
    rag_result = state.get("rag_result", "")
    macro_payload = state.get("macro_payload")
    forecast_payload = state.get("forecast_payload")
    churn_payload = state.get("churn_payload")
    kb_fragments = state.get("kb_fragments", "")

    # 组装给大模型的上下文（全部来自真实工具结果）
    context = "以下是为回答用户问题收集到的真实数据：\n"
    if macro_result:
        context += f"\n【宏观社零数据（SQL 查询）】\n{macro_result}\n"
    if forecast_result:
        context += f"\n【时序预测（ARIMA + 异常检测）】\n{forecast_result}\n"
    if churn_result:
        context += f"\n【用户流失预测（LightGBM 批量推理）】\n{churn_result}\n"
    if rag_result:
        context += f"\n【知识库检索（RAG）】\n{rag_result}\n"

    system_prompt = (
        "你是一名资深零售数据分析师。请严格基于下方提供的真实数据生成结构化分析报告。\n"
        "输出必须严格包含以下六个部分，标题一字不差、按顺序、缺一不可：\n"
        "【核心结论】\n【数据依据】\n【趋势与预测分析】\n【异常与风险】\n"
        "【建议的下一步分析】\n【结果限制与不确定性】\n"
        "（六个标题必须全部输出、一个都不能少，尤其不能遗漏最后的「【结果限制与不确定性】」）\n\n"
        "硬性约束：\n"
        "1. 只允许使用输入上下文中真实提供的数字，严禁自行计算、推断或编造数据；\n"
        "2. 某项数据未提供时必须写「暂无数据」，不得虚构；\n"
        "3. 数据依据引用真实查询结果，趋势部分引用真实预测值与置信区间，"
        "异常部分引用真实异常月份，流失部分引用真实风险分布；\n"
        "4. 直接输出报告正文，不要输出任何解释性前缀或后缀。\n\n"
        "结构化的行动建议：\n"
        "5. 在六段正文全部结束后，另起一行输出一个 JSON 数组，用 ```suggestions 开始、``` 结束；"
        "数组每个元素为一个行动建议对象，字段为：title（简短标题）、description（具体做什么）、"
        "rationale（原因）、evidence（可引用的真实数据依据，只能来自上方工具结果，无依据写「暂无数据」）、"
        "category（类别）、priority（优先级，取值：高/中/普通，无法判断时用「普通」）。\n"
        "6. 该数组应与【建议的下一步分析】章节内容保持一致，是该章节建议的结构化整理；"
        "建议数量 1~5 条，若确实没有可执行建议则输出空数组 []。"
    )

    generation_status = "success"
    fallback_reason = ""
    llm_report = ""
    suggestions = []

    try:
        llm_report = _llm_chat(
            system_prompt, f"用户问题：{query}\n\n{context}", temperature=0.2, timeout=120.0
        )
        print("  [Agent] 大模型报告已生成")
    except Exception as e:
        generation_status = "fallback"
        fallback_reason = classify_llm_error(e)
        print(f"  [Agent] 大模型报告生成失败，降级为模板报告。错误: {e}")

    # 提取结构化行动建议（从同一份大模型输出中剥离 JSON 块，不额外调用大模型）
    if generation_status == "success":
        llm_report, suggestions = _extract_suggestions(llm_report)

    # 格式校验：缺少核心章节（前五段）触发兜底；仅缺最后的「结果限制与不确定性」时补标准说明
    if generation_status == "success":
        sections = parse_report_sections(llm_report)
        present_titles = [s["title"] for s in sections]
        critical_missing = [t for t in SECTION_TITLES[:-1] if t not in present_titles]
        if not llm_report or critical_missing:
            generation_status = "fallback"
            fallback_reason = "大模型输出格式解析失败（缺少核心章节）"
            suggestions = []
            print("  [Agent] 大模型输出缺失核心章节，降级为模板报告。")
        elif "【结果限制与不确定性】" not in present_titles:
            llm_report = (llm_report.rstrip() + "\n\n【结果限制与不确定性】\n"
                          + "本报告由大模型基于真实工具结果生成；微观用户数据为模拟数据，"
                            "预测值与预测区间仅供参考，不构成经营决策的唯一依据。")
            print("  [Agent] 大模型输出缺失「结果限制与不确定性」，已补充标准说明。")

    if generation_status == "fallback":
        llm_report = build_fallback_report(macro_result, churn_result, forecast_result, rag_result)
        suggestions = []  # 模板兜底不伪造结构化行动建议

    # 关键数字覆盖检查（轻量，非事实校验，仅产生提示、不拦截报告）
    if generation_status == "success":
        fact_check = _check_fact_anchors(
            llm_report, _collect_fact_anchors(macro_payload, forecast_payload, churn_payload)
        )
        # 用户级字段覆盖核对：对报告中出现的用户，核对城市等级/年龄/流失概率与工具结果是否一致
        user_fields = _check_churn_user_fields(
            llm_report, _collect_churn_user_facts(churn_payload)
        )
        fact_check["user_fields"] = user_fields
        # 字段不一致时，把核对结果以受控说明追加到报告末尾（明确权威值，不简单替换原文）
        if user_fields.get("mismatches"):
            llm_report = _append_user_field_note(llm_report, user_fields["mismatches"])
    else:
        fact_check = {
            "status": "skipped", "checked": 0, "found": 0, "missing": [],
            "user_fields": {"status": "skipped", "checked": 0, "mismatches": [],
                            "reason": "模板兜底报告，未做大模型字段覆盖核对"},
        }

    final_report = "===== 零售业务智能洞察报告 =====\n\n" + llm_report
    report_sections = parse_report_sections(llm_report)

    # 组装统一执行追踪：意图识别 → 工具执行 → 报告生成
    execution_trace = [{
        "name": "intent_recognition",
        "input": {"query": query},
        "status": "success",
        "summary": f"识别意图为「{state.get('intent', '')}」（{state.get('intent_reason', '')}）",
        "error": "",
        "duration_ms": state.get("intent_duration_ms"),
        "sql": "",
        "source": "",
    }]
    execution_trace.extend(mcp_server.execution_log)
    execution_trace.append({
        "name": "report_generation",
        "input": {},
        "status": generation_status,
        "summary": "大模型生成报告" if generation_status == "success" else f"模板兜底报告（{fallback_reason}）",
        "error": fallback_reason if generation_status != "success" else "",
        "duration_ms": None,
        "sql": "",
        "source": "",
    })

    return {
        "final_report": final_report,
        "report_sections": report_sections,
        "suggestions": suggestions,
        "execution_trace": execution_trace,
        "kb_fragments": kb_fragments,
        "macro_payload": macro_payload,
        "forecast_payload": forecast_payload,
        "churn_payload": churn_payload,
        "fact_check": fact_check,
        "generation_status": generation_status,
        "fallback_reason": fallback_reason,
    }


def build_agent_workflow():
    workflow = StateGraph(AgentState)
    workflow.add_node("intent", analyze_intent_and_image)
    workflow.add_node("query_macro", query_macro)
    workflow.add_node("predict_churn", predict_churn)
    workflow.add_node("query_all", query_all)
    workflow.add_node("report", generate_report)
    workflow.set_entry_point("intent")
    workflow.add_conditional_edges("intent", route_after_intent, {
        "query_macro": "query_macro",
        "predict_churn": "predict_churn",
        "query_all": "query_all"
    })
    workflow.add_edge("query_macro", "report")
    workflow.add_edge("predict_churn", "report")
    workflow.add_edge("query_all", "report")
    workflow.add_edge("report", END)
    return workflow.compile()


def run_agent(query: str, image_base64: str = "") -> dict:
    """统一入口：重置执行日志后运行一次 Agent，返回完整结构化结果。"""
    mcp_server.reset_execution_log()
    app = build_agent_workflow()
    initial = {
        "query": query,
        "image_base64": image_base64,
        "final_report": "",
    }
    return app.invoke(initial)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    result = run_agent("结合宏观零售数据，给出当前用户流失预警和运营建议")
    print(result["final_report"])
    print("\n--- 执行追踪 ---")
    for rec in result.get("execution_trace", []):
        print(f"  [{rec['status']}] {rec['name']}: {rec['summary'][:60]} ({rec['duration_ms']}ms)")
