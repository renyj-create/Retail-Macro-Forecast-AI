# src/tests/test_agent.py
import os
import sys
import unittest
import sqlite3
import tempfile
import shutil

# 把项目根目录加入 sys.path，确保能导入 src
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from src.agents.tools import MCPToolServer
from src.agents.graph_workflow import (
    _rule_based_intent,
    build_fallback_report,
    parse_report_sections,
    SECTION_TITLES,
)


class TestAgent(unittest.TestCase):

    def setUp(self):
        self.mcp_server = MCPToolServer()
        # 使用临时数据库，避免污染真实的 retail.db
        self.test_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.test_dir, "test_retail.db")
        self.mcp_server.db_path = self.test_db_path

        conn = sqlite3.connect(self.test_db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS macro_retail_sales (
                date TEXT, retail_sales_current REAL, yoy_growth REAL
            )
        """)
        conn.execute("INSERT INTO macro_retail_sales VALUES ('2026-08-01', 39824.4, 0.4)")
        conn.execute("INSERT INTO macro_retail_sales VALUES ('2026-07-01', 39022.3, 0.6)")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_01_rule_based_intent(self):
        """规则意图识别（大模型不可用时的兜底）应正确覆盖三类问题。"""
        cases = [
            ("分析一下最近的宏观社零数据", "宏观分析"),
            ("帮我预测一下用户流失", "流失预测"),
            ("结合宏观数据，给出流失预警和运营建议", "综合分析"),
        ]
        for query, expected in cases:
            self.assertEqual(_rule_based_intent(query), expected, f"Query '{query}' 意图识别错误")

    def test_02_fallback_report(self):
        """模板兜底报告应包含六段式结构，且内容来自真实工具结果。"""
        report = build_fallback_report(
            macro_result="2026-08 社零总额 39824.4 亿元",
            churn_result="流失预测：共 4766 名用户",
            forecast_result="ARIMA 预测未来 3 个月",
            rag_result="知识库命中片段",
        )
        for title in SECTION_TITLES:
            self.assertIn(title, report, f"兜底报告缺少 {title}")
        self.assertIn("39824.4", report)

    def test_03_query_macro_sqlite(self):
        """SQL 查询工具：在临时数据库上验证真实 SQL 逻辑与结构化 payload。"""
        result, payload = self.mcp_server.query_macro_sqlite(limit=2)
        self.assertIn("39824.4", result)
        self.assertIn("0.4", result)

        # 结构化 payload 应包含真实数据与正确的月份格式（YYYY-MM）
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["date"], "2026-08")

        # 执行追踪应记录工具名 / 状态 / 耗时 / SQL
        rec = self.mcp_server._execution_summary("query_macro_sqlite")
        self.assertEqual(rec["status"], "success")
        self.assertIn("SELECT", rec["sql"])
        self.assertIsNotNone(rec["duration_ms"])

    def test_04_predict_churn_batch(self):
        """真实批量流失推理：应返回风险分布、特征归因与高风险用户。"""
        result, payload = self.mcp_server.predict_churn_batch(top_n=5)
        self.assertIn("风险分布", result)
        self.assertIsNotNone(payload)
        self.assertGreater(payload["total"], 0)
        self.assertIn("risk_distribution", payload)
        self.assertIn("feature_importance", payload)
        # 四档风险分段人数之和应等于样本总量
        self.assertEqual(
            sum(d["count"] for d in payload["risk_distribution"]),
            payload["total"],
        )

    def test_05_parse_report_sections(self):
        """六段式报告解析器应正确提取标题与内容。"""
        report = (
            "===== 报告 =====\n\n"
            "【核心结论】\n这是核心结论。\n\n"
            "【数据依据】\n这是数据依据。\n\n"
            "【趋势与预测分析】\n暂无数据\n\n"
            "【异常与风险】\n暂无数据\n\n"
            "【建议的下一步分析】\n建议A\n\n"
            "【结果限制与不确定性】\n限制B"
        )
        sections = parse_report_sections(report)
        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[0]["title"], "【核心结论】")
        self.assertIn("核心结论", sections[0]["content"])


if __name__ == "__main__":
    unittest.main()
