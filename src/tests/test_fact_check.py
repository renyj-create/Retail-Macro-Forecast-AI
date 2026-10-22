# src/tests/test_fact_check.py
"""
关键数字覆盖检查测试：锚点命中/部分缺失/全部缺失/无锚点/兜底，以及
generate_report 从 state 读取 payload（而非单例）与 kb_fragments 的传递。
不调用真实大模型。
"""
import os
import sys
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import src.agents.graph_workflow as gw
from src.agents.graph_workflow import (
    _collect_fact_anchors, _check_fact_anchors,
    _collect_churn_user_facts, _check_churn_user_fields,
)


def six_section_body():
    return (
        "【核心结论】\n测试结论\n\n"
        "【数据依据】\n测试数据\n\n"
        "【趋势与预测分析】\n测试趋势\n\n"
        "【异常与风险】\n测试风险\n\n"
        "【建议的下一步分析】\n测试建议\n\n"
        "【结果限制与不确定性】\n测试限制"
    )


class TestFactAnchors(unittest.TestCase):

    def test_collect_anchors_from_payloads(self):
        anchors = _collect_fact_anchors(
            [{"date": "2026-08", "value": 39824.4, "yoy": 0.4}],
            {"forecast_values": [40233.6]},
            {"total": 4766},
        )
        self.assertEqual(anchors, ["39824.4", "40233.6", "4766"])

    def test_collect_anchors_empty_payloads(self):
        self.assertEqual(_collect_fact_anchors([], None, None), [])

    def test_check_all_hit_ok(self):
        r = _check_fact_anchors("...39824.4...40233.6...4766...", ["39824.4", "40233.6", "4766"])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["checked"], 3)
        self.assertEqual(r["found"], 3)
        self.assertEqual(r["missing"], [])

    def test_check_partial_missing_warning(self):
        r = _check_fact_anchors("...39824.4...", ["39824.4", "40233.6"])
        self.assertEqual(r["status"], "warning")
        self.assertEqual(r["missing"], ["40233.6"])

    def test_check_all_missing_warning(self):
        r = _check_fact_anchors("没有数字的报告", ["39824.4"])
        self.assertEqual(r["status"], "warning")
        self.assertEqual(r["missing"], ["39824.4"])

    def test_check_no_anchors_skipped(self):
        r = _check_fact_anchors("任何文本", [])
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(r["reason"], "无可检查的关键数字锚点")


class TestGenerateReportFactCheck(unittest.TestCase):

    def setUp(self):
        gw.mcp_server.reset_execution_log()

    def _state(self, **overrides):
        s = {"query": "测试"}
        s.update(overrides)
        return s

    def test_success_all_anchors_present(self):
        state = self._state(
            macro_payload=[{"date": "2026-08", "value": 39824.4, "yoy": 0.4}],
            forecast_payload={"forecast_values": [40233.6]},
            churn_payload={"total": 4766},
        )
        report = six_section_body() + "\n\n数据：39824.4 亿元；预测 40233.6；样本 4766。"
        with patch.object(gw, "_llm_chat", return_value=report):
            res = gw.generate_report(state)
        self.assertEqual(res["generation_status"], "success")
        self.assertEqual(res["fact_check"]["status"], "ok")

    def test_uses_state_payloads_not_singleton(self):
        # 单例里放“干扰”值，state 里放正确值，验证报告只读 state
        gw.mcp_server.last_macro_payload = [{"date": "2020-01", "value": 11111.1, "yoy": 9.9}]
        gw.mcp_server.last_forecast_payload = {"forecast_values": [22222.2]}
        state = self._state(
            macro_payload=[{"date": "2026-08", "value": 39824.4, "yoy": 0.4}],
            forecast_payload={"forecast_values": [40233.6]},
            churn_payload=None,
        )
        report = six_section_body() + "\n\n39824.4 ... 40233.6"
        with patch.object(gw, "_llm_chat", return_value=report):
            res = gw.generate_report(state)
        self.assertEqual(res["fact_check"]["status"], "ok")
        self.assertEqual(res["macro_payload"], state["macro_payload"])
        self.assertEqual(res["forecast_payload"], state["forecast_payload"])

    def test_kb_fragments_from_state(self):
        state = self._state(kb_fragments="来自state的片段")
        with patch.object(gw, "_llm_chat", return_value=six_section_body()):
            res = gw.generate_report(state)
        self.assertEqual(res["kb_fragments"], "来自state的片段")

    def test_fallback_skipped(self):
        with patch.object(gw, "_llm_chat", side_effect=RuntimeError("boom")):
            res = gw.generate_report(self._state())
        self.assertEqual(res["generation_status"], "fallback")
        self.assertEqual(res["fact_check"]["status"], "skipped")

    def test_intent_node_passes_kb_fragments_from_return(self):
        # rag_search 返回 (text, fragments)，intent 节点应把 fragments 写入 state
        with patch.object(gw.mcp_server, "rag_search",
                          return_value=("【企业知识库检索结果】\n片段", "片段")), \
             patch.object(gw, "_llm_chat", return_value="宏观分析"):
            res = gw.analyze_intent_and_image({"query": "测试", "image_base64": ""})
        self.assertEqual(res["kb_fragments"], "片段")
        self.assertEqual(res["rag_result"], "【企业知识库检索结果】\n片段")


class TestChurnUserFields(unittest.TestCase):
    """用户级字段覆盖核对：城市等级不一致 / 数值字段不一致 / 用户ID错配 / 正确通过。"""

    def _facts(self):
        return [
            {"user_id": "10407", "city_tier": "三线", "age": 32, "churn_prob_pct": "32.2%"},
            {"user_id": "14921", "city_tier": "三线", "age": 27, "churn_prob_pct": "32.2%"},
            {"user_id": "12650", "city_tier": "二线", "age": 45, "churn_prob_pct": "32.2%"},
        ]

    def test_collect_facts_from_payload(self):
        payload = {"top_risk_users": [
            {"user_id": 10407, "city_tier": "三线", "age": 32, "churn_prob": 0.3217},
        ]}
        facts = _collect_churn_user_facts(payload)
        self.assertEqual(facts[0]["user_id"], "10407")
        self.assertEqual(facts[0]["city_tier"], "三线")
        self.assertEqual(facts[0]["age"], 32)
        self.assertEqual(facts[0]["churn_prob_pct"], "32.2%")

    def test_city_tier_mismatch(self):
        report = "用户10407（二线，32岁）流失概率 32.2%"
        r = _check_churn_user_fields(report, self._facts())
        self.assertEqual(r["status"], "warning")
        self.assertTrue(any(
            m["field"] == "city_tier" and m["user_id"] == "10407" and m["expected"] == "三线"
            for m in r["mismatches"]
        ))

    def test_numeric_field_mismatch(self):
        # 年龄写错：正确 32，报告写 45
        report = "用户10407（三线，45岁）流失概率 32.2%"
        r = _check_churn_user_fields(report, self._facts())
        self.assertEqual(r["status"], "warning")
        self.assertTrue(any(
            m["field"] == "age" and m["user_id"] == "10407" and m["found"] == "45"
            for m in r["mismatches"]
        ))

    def test_user_id_field_mismap(self):
        # 把用户 12650 的年龄(45)错配到 10407 身上，反之亦然
        report = "用户10407（三线，45岁）、用户12650（二线，32岁）"
        r = _check_churn_user_fields(report, self._facts())
        self.assertEqual(r["status"], "warning")
        self.assertTrue(any(m["user_id"] == "10407" and m["field"] == "age" for m in r["mismatches"]))
        self.assertTrue(any(m["user_id"] == "12650" and m["field"] == "age" for m in r["mismatches"]))

    def test_correct_report_passes(self):
        report = "用户10407（三线，32岁）、用户14921（三线，27岁）、用户12650（二线，45岁），流失概率均为 32.2%"
        r = _check_churn_user_fields(report, self._facts())
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["mismatches"], [])

    def test_empty_facts_skipped(self):
        r = _check_churn_user_fields("任何文本", [])
        self.assertEqual(r["status"], "skipped")


class TestGenerateReportUserFieldNote(unittest.TestCase):

    def setUp(self):
        gw.mcp_server.reset_execution_log()

    def test_user_field_mismatch_appends_note(self):
        state = {
            "query": "测试",
            "macro_payload": [{"date": "2026-08", "value": 39824.4, "yoy": 0.4}],
            "forecast_payload": {"forecast_values": [40233.6]},
            "churn_payload": {
                "total": 4766,
                "top_risk_users": [
                    {"user_id": 10407, "city_tier": "三线", "age": 32, "churn_prob": 0.3217},
                ],
            },
        }
        report = (six_section_body()
                  + "\n\n用户10407（二线，32岁）流失概率 32.2%，样本 4766。39824.4 40233.6")
        with patch.object(gw, "_llm_chat", return_value=report):
            res = gw.generate_report(state)
        # 数字锚点仍全部命中 → 数字覆盖检查 ok
        self.assertEqual(res["fact_check"]["status"], "ok")
        # 用户级字段覆盖核对发现城市等级不一致 → warning
        self.assertEqual(res["fact_check"]["user_fields"]["status"], "warning")
        self.assertTrue(any(
            m["field"] == "city_tier" for m in res["fact_check"]["user_fields"]["mismatches"]
        ))
        # 不一致字段以受控说明追加到报告末尾，明确权威值
        self.assertIn("字段核对提示", res["final_report"])
        self.assertIn("工具结果为「三线」", res["final_report"])

    def test_user_field_consistent_no_note(self):
        state = {
            "query": "测试",
            "macro_payload": [{"date": "2026-08", "value": 39824.4, "yoy": 0.4}],
            "forecast_payload": {"forecast_values": [40233.6]},
            "churn_payload": {
                "total": 4766,
                "top_risk_users": [
                    {"user_id": 10407, "city_tier": "三线", "age": 32, "churn_prob": 0.3217},
                ],
            },
        }
        report = (six_section_body()
                  + "\n\n用户10407（三线，32岁）流失概率 32.2%，样本 4766。39824.4 40233.6")
        with patch.object(gw, "_llm_chat", return_value=report):
            res = gw.generate_report(state)
        self.assertEqual(res["fact_check"]["user_fields"]["status"], "ok")
        self.assertNotIn("字段核对提示", res["final_report"])


if __name__ == "__main__":
    unittest.main()
