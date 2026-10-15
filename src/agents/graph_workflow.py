# src/agents/graph_workflow.py
import os
import sys
import time

# 🌟 核心：将项目根目录加入 Python 搜索路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from typing import TypedDict
from langgraph.graph import StateGraph, END
from openai import OpenAI
from dotenv import load_dotenv
from src.agents.tools import MCPToolServer

# 🌟 加载 .env 文件中的环境变量
load_dotenv(os.path.join(BASE_DIR, '.env'))

API_KEY = os.getenv("DASHSCOPE_API_KEY")
MODEL_NAME = os.getenv("QWEN_MODEL", "qwen3.7-flash")

# 🌟 报告六段式结构（标题必须与解析器严格一致）
SECTION_TITLES = [
    "【核心结论】",
    "【数据依据】",
    "【趋势与预测分析】",
    "【异常与风险】",
    "【建议的下一步分析】",
    "【结果限制与不确定性】",
]

# 初始化大模型客户端（API Key 缺失时允许模块加载，调用时再降级）
client = None
if API_KEY:
    try:
        client = OpenAI(
            api_key=API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=30.0,
        )
    except Exception as e:
        print(f"[Agent] 初始化大模型客户端失败: {e}")

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


def _llm_chat(system_prompt: str, user_content: str, temperature: float = 0.2,
              timeout: float = 30.0):
    """统一的大模型调用封装，异常时抛出以便上层降级。"""
    if client is None:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，大模型不可用")
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
    rag_result = mcp_server.rag_search(query)

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
    macro_result = mcp_server.query_macro_sqlite(limit=12)
    forecast_result = mcp_server.forecast_timeseries()
    return {
        "macro_result": macro_result,
        "forecast_result": forecast_result,
    }


def predict_churn(state: AgentState):
    """流失预测：真实 LightGBM 批量推理。"""
    return {"churn_result": mcp_server.predict_churn_batch(top_n=20)}


def query_all(state: AgentState):
    """综合分析：宏观 + 时序预测 + 流失批量推理组合。"""
    return {
        "macro_result": mcp_server.query_macro_sqlite(limit=12),
        "forecast_result": mcp_server.forecast_timeseries(),
        "churn_result": mcp_server.predict_churn_batch(top_n=20),
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
    if any(k in msg for k in ("未配置", "dashscope_api_key", "api key not")):
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


def generate_report(state: AgentState):
    print("[Agent] 正在生成结构化诊断报告...")
    query = state.get("query", "")
    macro_result = state.get("macro_result", "")
    churn_result = state.get("churn_result", "")
    forecast_result = state.get("forecast_result", "")
    rag_result = state.get("rag_result", "")

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
        "【建议的下一步分析】\n【结果限制与不确定性】\n\n"
        "硬性约束：\n"
        "1. 只允许使用输入上下文中真实提供的数字，严禁自行计算、推断或编造数据；\n"
        "2. 某项数据未提供时必须写「暂无数据」，不得虚构；\n"
        "3. 数据依据引用真实查询结果，趋势部分引用真实预测值与置信区间，"
        "异常部分引用真实异常月份，流失部分引用真实风险分布；\n"
        "4. 直接输出报告正文，不要输出任何解释性前缀或后缀。"
    )

    generation_status = "success"
    fallback_reason = ""
    llm_report = ""

    try:
        llm_report = _llm_chat(
            system_prompt, f"用户问题：{query}\n\n{context}", temperature=0.2, timeout=120.0
        )
        print("  [Agent] 大模型报告已生成")
    except Exception as e:
        generation_status = "fallback"
        fallback_reason = classify_llm_error(e)
        print(f"  [Agent] 大模型报告生成失败，降级为模板报告。错误: {e}")

    # 格式校验：缺少六段结构时触发兜底
    if generation_status == "success":
        sections = parse_report_sections(llm_report)
        if len(sections) < len(SECTION_TITLES) or not llm_report:
            generation_status = "fallback"
            fallback_reason = "大模型输出格式解析失败（缺少六段结构）"
            print("  [Agent] 大模型输出缺失六段结构，降级为模板报告。")

    if generation_status == "fallback":
        llm_report = build_fallback_report(macro_result, churn_result, forecast_result, rag_result)

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
        "execution_trace": execution_trace,
        "kb_fragments": mcp_server.last_kb_fragments,
        "macro_payload": mcp_server.last_macro_payload,
        "forecast_payload": mcp_server.last_forecast_payload,
        "churn_payload": mcp_server.last_churn_payload,
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
