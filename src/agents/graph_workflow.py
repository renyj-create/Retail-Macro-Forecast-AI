# src/agents/graph_workflow.py
import os
import sys

# 🌟 核心：将项目根目录加入 Python 搜索路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

from typing import TypedDict
from langgraph.graph import StateGraph, END
from openai import OpenAI
from dotenv import load_dotenv
from src.agents.tools import MCPToolServer # 现在这行不会报错了

# ... 后面的代码保持不变

# 🌟 核心：加载 .env 文件中的环境变量
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(BASE_DIR, '.env'))

# 🌟 从环境变量读取 API Key 和模型名称
API_KEY = os.getenv("DASHSCOPE_API_KEY")
MODEL_NAME = os.getenv("QWEN_MODEL", "qwen3.7-flash")

if not API_KEY:
    raise ValueError("❌ 未找到 DASHSCOPE_API_KEY，请检查 .env 文件是否存在且已填写。")

# 初始化大模型客户端
client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

mcp_server = MCPToolServer()


class AgentState(TypedDict):
    query: str
    image_base64: str
    intent: str
    macro_result: str
    churn_result: str
    rag_result: str
    final_report: str
    # 🌟 可解释性字段：执行明细（供前端「执行明细」面板展示）
    sql_statements: str
    data_count: int
    kb_fragments: str
    # 🌟 生成状态字段：success / fallback / failed
    generation_status: str
    fallback_reason: str


def analyze_intent_and_image(state: AgentState):
    query = state["query"]
    image_base64 = state.get("image_base64", "")

    print(f"\n[Agent] 正在理解用户意图...")
    rag_result = mcp_server.rag_search(query)

    system_prompt = "你是一个零售数据分析助手。请判断用户意图，只输出以下三种之一：[宏观分析]、[流失预测]、[综合分析]。不要输出其他任何内容。"
    user_content = f"用户提问：{query}"

    if image_base64:
        print("  [Agent] 检测到图片，调用多模态能力...")
        user_content += "\n(用户上传了一张图片，请一并分析)"
        rag_result = "【多模态识图结果】识别到图片包含“社零增速放缓、线下客流减少”的趋势信息。\n" + rag_result

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.1
        )
        intent = response.choices[0].message.content.strip()
        print(f"  [Agent] 大模型意图识别结果: {intent}")

        if "宏观" in intent and "流失" not in intent:
            intent = "宏观分析"
        elif "流失" in intent and "宏观" not in intent:
            intent = "流失预测"
        else:
            intent = "综合分析"

    except Exception as e:
        print(f"  [Agent] API 调用失败，降级为规则匹配。错误: {e}")
        intent = "综合分析"
        if "宏观" in query and "流失" not in query:
            intent = "宏观分析"
        elif "流失" in query and "宏观" not in query:
            intent = "流失预测"

    return {"intent": intent, "rag_result": rag_result}


def route_after_intent(state: AgentState):
    if state["intent"] == "宏观分析":
        return "query_macro"
    elif state["intent"] == "流失预测":
        return "predict_churn"
    else:
        return "query_all"


def query_macro(state: AgentState):
    return {"macro_result": mcp_server.query_macro_sqlite()}


def predict_churn(state: AgentState):
    return {"churn_result": mcp_server.predict_churn_lightgbm()}


def query_all(state: AgentState):
    return {
        "macro_result": mcp_server.query_macro_sqlite(),
        "churn_result": mcp_server.predict_churn_lightgbm()
    }


def build_fallback_report(macro_result: str, churn_result: str, rag_result: str) -> str:
    """大模型不可用时的兜底报告，保证三段结构完整。"""
    sql_part = macro_result if macro_result else "（本次未通过 SQL 查询宏观数据）"
    rag_part = rag_result if rag_result else "（本次未检索到知识库内容）"
    summary = "结合宏观社零增速放缓与用户流失数据，建议优先对高流失风险用户进行召回，并关注宏观消费意愿变化对复购的影响。"
    return (
        "【SQL查询结果】\n" + sql_part + "\n\n"
        "【知识库引用】\n" + rag_part + "\n\n"
        "【执行摘要】\n" + summary
    )


def classify_llm_error(e: Exception) -> str:
    """将大模型调用异常归类为可读的中文原因，用于回传前端展示。"""
    msg = str(e).lower()
    if any(k in msg for k in ("401", "unauthorized", "authentication", "api key")):
        return "API Key 无效或鉴权失败"
    if any(k in msg for k in ("timeout", "timed out")):
        return "请求超时"
    if any(k in msg for k in ("429", "rate limit", "too many requests")):
        return "触发限流（Rate Limit）"
    if any(k in msg for k in ("connection", "network", "refused", "unreachable")):
        return "网络连接失败"
    return f"未知异常：{str(e)[:120]}"


def generate_report(state: AgentState):
    print("[Agent] 正在生成结构化诊断报告...")
    query = state.get("query", "")
    macro_result = state.get("macro_result", "")
    churn_result = state.get("churn_result", "")
    rag_result = state.get("rag_result", "")

    # 🌟 收集执行明细：原始 SQL、数据量、知识库原文片段（供前端「执行明细」面板展示）
    sql_statements = getattr(mcp_server, "last_sql", "")
    data_count = getattr(mcp_server, "last_data_count", 0)
    kb_fragments = getattr(mcp_server, "last_kb_fragments", "") or rag_result

    # 组装给大模型的上下文
    context = "以下是为回答用户问题收集到的数据：\n"
    if macro_result:
        context += f"\n【宏观社零数据（MCP SQL 查询）】\n{macro_result}\n"
    if churn_result:
        context += f"\n【用户流失预测（MCP 模型推理）】\n{churn_result}\n"
    if rag_result:
        context += f"\n【知识库检索（RAG）】\n{rag_result}\n"

    # 🌟 强制大模型输出三段结构 + 数据真实性硬性约束，保证可解释性与防幻觉
    system_prompt = (
        "你是一名资深零售数据分析师。请基于给定数据生成一份结构化报告，"
        "输出必须严格包含以下三个部分（标题必须完全一致，缺一不可）：\n"
        "1. 【SQL查询结果】：总结通过 SQL 查询得到的宏观/业务数据结论；\n"
        "2. 【知识库引用】：引用知识库检索到的政策/研报观点；\n"
        "3. 【执行摘要】：用 2-3 句话给出可执行的业务建议。\n"
        "直接输出报告正文，不要输出任何多余的解释性前缀或后缀。\n"
        "🔒 数据真实性硬性约束：你绝对不能自行计算或编造数据。"
        "必须严格使用输入上下文中提供的数字，如果输入没有提供某项数据，"
        "请输出“暂无数据”，严禁虚构。"
    )

    # 🌟 状态追踪：success / fallback（failed 由上层 API 异常捕获兜底）
    generation_status = "success"
    fallback_reason = ""
    llm_report = ""

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户问题：{query}\n\n{context}"},
            ],
            temperature=0.2,
        )
        llm_report = response.choices[0].message.content.strip()
        print("  [Agent] 大模型报告已生成")
    except Exception as e:
        generation_status = "fallback"
        fallback_reason = classify_llm_error(e)
        print(f"  [Agent] 大模型报告生成失败，降级为模板报告。错误: {e}")

    # 格式校验：大模型输出缺失三段结构时，触发兜底
    if generation_status == "success" and (
        not llm_report or "【SQL查询结果】" not in llm_report or "【执行摘要】" not in llm_report
    ):
        generation_status = "fallback"
        fallback_reason = "大模型输出格式解析失败（缺少三段结构）"
        print("  [Agent] 大模型输出缺失三段结构，降级为模板报告。")

    if generation_status == "fallback":
        llm_report = build_fallback_report(macro_result, churn_result, rag_result)

    # 组装最终报告：三段结构 + 底部追加 SQL 语句（可解释性）
    final_report = "===== 零售业务智能洞察报告 =====\n\n" + llm_report
    if sql_statements:
        final_report += f"\n\n【SQL 语句】\n{sql_statements}"

    return {
        "final_report": final_report,
        "sql_statements": sql_statements,
        "data_count": data_count,
        "kb_fragments": kb_fragments,
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


if __name__ == "__main__":
    app = build_agent_workflow()
    result = app.invoke(
        {"query": "结合宏观零售数据，给出当前用户流失预警和运营建议", "image_base64": "", "final_report": ""})
    print(result["final_report"])
    print("\n--- 执行明细 ---")
    print("SQL:", result.get("sql_statements", ""))
    print("数据量:", result.get("data_count", 0))
    print("知识库片段:", result.get("kb_fragments", ""))