# src/tests/test_workflow.py
"""
LangGraph 工作流测试：覆盖意图路由、真实工具调用与报告降级。

测试不依赖外部大模型 API（通过将 graph_workflow.client 置空，强制走
规则降级 + 模板兜底），确保在无网络 / 无 Key 环境下仍可稳定验证执行链路。
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import src.agents.graph_workflow as gw
from src.agents.graph_workflow import run_agent
from unittest.mock import patch

# 模拟大模型：意图识别时误判为「综合分析」，报告生成仍返回合法六段式
_SIX_SECTION_REPORT = (
    "【核心结论】\n测试结论\n\n"
    "【数据依据】\n暂无数据\n\n"
    "【趋势与预测分析】\n暂无数据\n\n"
    "【异常与风险】\n暂无数据\n\n"
    "【建议的下一步分析】\n建议\n\n"
    "【结果限制与不确定性】\n限制"
)


def _fake_llm_misclassified(system_prompt, user_content, **kw):
    if "判断用户意图" in system_prompt:
        return "综合分析"
    return _SIX_SECTION_REPORT


class TestWorkflow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # 强制大模型不可用，走规则意图识别 + 模板兜底，保证测试确定性
        cls._saved_client = gw.client
        gw.client = None

    @classmethod
    def tearDownClass(cls):
        gw.client = cls._saved_client

    def _tool_names(self, result):
        return [rec["name"] for rec in result.get("execution_trace", [])]

    def test_01_macro_intent_routes_to_macro_and_forecast(self):
        """宏观分析意图：应执行 SQL 查询 + 时序预测，不执行流失预测。"""
        result = run_agent("分析最近社零数据走势，识别异常变化")
        self.assertEqual(result["intent"], "宏观分析")
        names = self._tool_names(result)
        self.assertIn("query_macro_sqlite", names)
        self.assertIn("forecast_timeseries", names)
        self.assertNotIn("predict_churn_batch", names)
        # 结构化 payload 应存在
        self.assertIsNotNone(result.get("forecast_payload"))
        self.assertIsNone(result.get("churn_payload"))

    def test_02_churn_intent_routes_to_batch_inference(self):
        """流失预测意图：应执行批量流失推理，不执行宏观/时序预测。"""
        result = run_agent("分析用户流失预测结果，展示风险分布和主要影响特征")
        self.assertEqual(result["intent"], "流失预测")
        names = self._tool_names(result)
        self.assertIn("predict_churn_batch", names)
        self.assertNotIn("query_macro_sqlite", names)
        self.assertNotIn("forecast_timeseries", names)
        self.assertIsNotNone(result.get("churn_payload"))

    def test_03_comprehensive_intent_routes_to_all_tools(self):
        """综合分析意图：应组合宏观 + 时序预测 + 流失批量推理。"""
        result = run_agent("结合宏观零售数据和用户流失情况给出运营建议")
        self.assertEqual(result["intent"], "综合分析")
        names = self._tool_names(result)
        for expected in ("query_macro_sqlite", "forecast_timeseries", "predict_churn_batch"):
            self.assertIn(expected, names)

    def test_04_fallback_report_generation(self):
        """大模型不可用时，报告应降级为模板兜底并如实标注状态。"""
        result = run_agent("分析最近社零数据走势")
        self.assertEqual(result["generation_status"], "fallback")
        self.assertTrue(result["fallback_reason"])
        # 六段式结构完整
        self.assertEqual(len(result["report_sections"]), len(gw.SECTION_TITLES))

    def test_05_execution_trace_complete(self):
        """执行追踪应包含意图识别与报告生成两个节点，且所有工具状态明确。"""
        result = run_agent("结合宏观零售数据给出流失预警")
        names = self._tool_names(result)
        self.assertEqual(names[0], "intent_recognition")
        self.assertEqual(names[-1], "report_generation")
        for rec in result["execution_trace"]:
            self.assertIn(rec["status"], ("success", "failed", "fallback", "not_configured"))
            self.assertIn("name", rec)
            self.assertIn("summary", rec)

    def test_06_macro_question_not_misrouted_to_churn(self):
        """宏观单域问题即使大模型误判为综合分析，也不应调用流失预测。"""
        with patch.object(gw, "_llm_chat", side_effect=_fake_llm_misclassified):
            result = run_agent("分析最近社零数据走势，识别异常变化，并给出有数据依据的分析建议。")
        self.assertEqual(result["intent"], "宏观分析")
        names = self._tool_names(result)
        self.assertNotIn("predict_churn_batch", names)
        self.assertIn("query_macro_sqlite", names)
        self.assertIn("forecast_timeseries", names)

    def test_07_churn_question_not_misrouted_to_macro(self):
        """流失单域问题即使大模型误判为综合分析，也应只调用流失预测。"""
        with patch.object(gw, "_llm_chat", side_effect=_fake_llm_misclassified):
            result = run_agent("分析用户流失预测结果，展示风险分布和主要影响特征")
        self.assertEqual(result["intent"], "流失预测")
        names = self._tool_names(result)
        self.assertIn("predict_churn_batch", names)
        self.assertNotIn("query_macro_sqlite", names)
        self.assertNotIn("forecast_timeseries", names)

    def test_08_trend_question_calls_forecast(self):
        """宏观趋势问题应调用时序预测能力，不调用流失预测。"""
        with patch.object(gw, "_llm_chat", side_effect=_fake_llm_misclassified):
            result = run_agent("基于现有历史数据预测未来三个月社零走势，展示预测结果及模型评估信息。")
        self.assertEqual(result["intent"], "宏观分析")
        names = self._tool_names(result)
        self.assertIn("forecast_timeseries", names)
        self.assertNotIn("predict_churn_batch", names)

    def test_09_comprehensive_question_still_runs_all(self):
        """双域综合问题信任大模型综合分析，仍编排全部相关工具。"""
        with patch.object(gw, "_llm_chat", side_effect=_fake_llm_misclassified):
            result = run_agent("结合宏观零售数据和用户流失情况，给出可执行的经营建议。")
        self.assertEqual(result["intent"], "综合分析")
        names = self._tool_names(result)
        for expected in ("query_macro_sqlite", "forecast_timeseries", "predict_churn_batch"):
            self.assertIn(expected, names)

    def test_10_reconcile_intent(self):
        """_reconcile_intent：单域问题用规则结果，双域/无关键词信任大模型。"""
        from src.agents.graph_workflow import _reconcile_intent
        self.assertEqual(_reconcile_intent("分析最近社零数据走势", "综合分析"), "宏观分析")
        self.assertEqual(_reconcile_intent("分析用户流失预测结果", "综合分析"), "流失预测")
        self.assertEqual(_reconcile_intent("分析最近社零数据走势", "宏观分析"), "宏观分析")
        self.assertEqual(_reconcile_intent("分析用户流失预测结果", "流失预测"), "流失预测")
        self.assertEqual(_reconcile_intent("结合宏观零售数据和用户流失情况", "综合分析"), "综合分析")
        self.assertEqual(_reconcile_intent("结合宏观零售数据和用户流失情况", None), "综合分析")


if __name__ == "__main__":
    unittest.main()
