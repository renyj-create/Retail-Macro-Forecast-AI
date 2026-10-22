# src/tests/test_suggestions.py
"""
结构化行动建议解析测试：覆盖正常解析、格式异常兜底、归一化与 generate_report 集成。
不调用真实大模型，全部使用确定性输入。
"""
import os
import sys
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import src.agents.graph_workflow as gw
from src.agents.graph_workflow import _extract_suggestions, _normalize_suggestions


def six_section_body():
    return (
        "【核心结论】\n核心结论测试\n\n"
        "【数据依据】\n数据依据测试\n\n"
        "【趋势与预测分析】\n趋势测试\n\n"
        "【异常与风险】\n风险测试\n\n"
        "【建议的下一步分析】\n建议测试\n\n"
        "【结果限制与不确定性】\n限制测试"
    )


SUGGESTION_JSON = (
    '[{"title": "关注高流失用户", "description": "复核 Top20 高风险用户", '
    '"rationale": "流失概率偏高", "evidence": "LightGBM 推理显示存在极高风险用户", '
    '"category": "流失运营", "priority": "高"}]'
)


class TestExtractSuggestions(unittest.TestCase):

    def test_extract_valid_block(self):
        text = six_section_body() + "\n\n```suggestions\n" + SUGGESTION_JSON + "\n```"
        clean, sugg = _extract_suggestions(text)
        self.assertEqual(len(sugg), 1)
        self.assertEqual(sugg[0]["title"], "关注高流失用户")
        self.assertEqual(sugg[0]["priority"], "高")
        self.assertNotIn("```suggestions", clean)
        # 剥离后正文仍包含六段
        self.assertIn("【核心结论】", clean)
        self.assertIn("【结果限制与不确定性】", clean)

    def test_extract_no_block_returns_empty(self):
        text = six_section_body()
        clean, sugg = _extract_suggestions(text)
        self.assertEqual(sugg, [])
        self.assertEqual(clean, text)

    def test_extract_malformed_json_returns_empty_but_strips(self):
        text = six_section_body() + "\n\n```suggestions\n{not valid json\n```"
        clean, sugg = _extract_suggestions(text)
        self.assertEqual(sugg, [])
        self.assertNotIn("```suggestions", clean)


class TestNormalizeSuggestions(unittest.TestCase):

    def test_missing_keys_get_defaults(self):
        out = _normalize_suggestions([{"title": "t"}])
        self.assertEqual(len(out), 1)
        s = out[0]
        self.assertEqual(s["title"], "t")
        self.assertEqual(s["description"], "")
        self.assertEqual(s["rationale"], "")
        self.assertEqual(s["evidence"], "")
        self.assertEqual(s["category"], "")
        self.assertEqual(s["priority"], "普通")  # 缺省优先级

    def test_invalid_priority_falls_back_to_normal(self):
        out = _normalize_suggestions([{"title": "t", "priority": "紧急"}])
        self.assertEqual(out[0]["priority"], "普通")

    def test_empty_suggestions_dropped(self):
        out = _normalize_suggestions([{"title": "", "description": ""}, {"title": "x"}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "x")

    def test_caps_at_five(self):
        raw = [{"title": f"t{i}"} for i in range(10)]
        out = _normalize_suggestions(raw)
        self.assertEqual(len(out), 5)

    def test_non_list_returns_empty(self):
        self.assertEqual(_normalize_suggestions({"a": 1}), [])
        self.assertEqual(_normalize_suggestions("x"), [])


class TestGenerateReportIntegration(unittest.TestCase):

    def setUp(self):
        gw.mcp_server.reset_execution_log()

    def test_generate_report_parses_suggestions(self):
        text = six_section_body() + "\n\n```suggestions\n" + SUGGESTION_JSON + "\n```"
        with patch.object(gw, "_llm_chat", return_value=text):
            result = gw.generate_report({"query": "测试"})
        self.assertEqual(result["generation_status"], "success")
        self.assertEqual(len(result["suggestions"]), 1)
        self.assertEqual(result["suggestions"][0]["title"], "关注高流失用户")
        self.assertNotIn("```suggestions", result["final_report"])
        self.assertEqual(len(result["report_sections"]), 6)

    def test_generate_report_malformed_suggestions_keeps_report(self):
        text = six_section_body() + "\n\n```suggestions\n{broken\n```"
        with patch.object(gw, "_llm_chat", return_value=text):
            result = gw.generate_report({"query": "测试"})
        # 报告仍成功、六段完整，仅建议为空
        self.assertEqual(result["generation_status"], "success")
        self.assertEqual(result["suggestions"], [])
        self.assertEqual(len(result["report_sections"]), 6)

    def test_generate_report_fallback_has_no_suggestions(self):
        with patch.object(gw, "_llm_chat", side_effect=RuntimeError("boom")):
            result = gw.generate_report({"query": "测试"})
        self.assertEqual(result["generation_status"], "fallback")
        self.assertEqual(result["suggestions"], [])
        self.assertEqual(len(result["report_sections"]), 6)

    def test_generate_report_autofills_missing_disclaimer(self):
        # 仅缺最后的【结果限制与不确定性】，应补标准说明而非整体兜底
        five_sections = (
            "【核心结论】\n结论\n\n"
            "【数据依据】\n数据\n\n"
            "【趋势与预测分析】\n趋势\n\n"
            "【异常与风险】\n风险\n\n"
            "【建议的下一步分析】\n建议"
        )
        with patch.object(gw, "_llm_chat", return_value=five_sections):
            result = gw.generate_report({"query": "测试"})
        self.assertEqual(result["generation_status"], "success")
        self.assertEqual(len(result["report_sections"]), 6)
        self.assertEqual(result["report_sections"][-1]["title"], "【结果限制与不确定性】")

    def test_generate_report_missing_core_section_falls_back(self):
        # 缺核心章节（如【数据依据】）应整体兜底
        broken = (
            "【核心结论】\n结论\n\n"
            "【趋势与预测分析】\n趋势\n\n"
            "【异常与风险】\n风险\n\n"
            "【建议的下一步分析】\n建议\n\n"
            "【结果限制与不确定性】\n限制"
        )
        with patch.object(gw, "_llm_chat", return_value=broken):
            result = gw.generate_report({"query": "测试"})
        self.assertEqual(result["generation_status"], "fallback")


if __name__ == "__main__":
    unittest.main()
