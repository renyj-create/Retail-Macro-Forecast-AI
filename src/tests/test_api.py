# src/tests/test_api.py
"""
FastAPI 集成测试：使用 TestClient 覆盖主要接口的真实执行路径。

同样通过将 graph_workflow.client 置空，避免依赖外部大模型 API。
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import src.agents.graph_workflow as gw


class TestAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._saved_client = gw.client
        gw.client = None
        # 隔离 RAG 的 Chroma 持久化目录，避免污染真实 chroma_db
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._saved_chroma_path = gw.mcp_server.chroma_path
        gw.mcp_server.chroma_path = os.path.join(cls._tmpdir.name, "chroma_db")
        from fastapi.testclient import TestClient
        from src.api.main import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        gw.client = cls._saved_client
        gw.mcp_server.chroma_path = cls._saved_chroma_path
        cls._tmpdir.cleanup()

    def test_01_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_02_forecast(self):
        r = self.client.get("/api/v1/forecast")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertGreater(len(d["historical_dates"]), 0)
        self.assertEqual(len(d["forecast_dates"]), 3)
        self.assertEqual(len(d["forecast_values"]), 3)
        self.assertIn("mape", d["metrics"])

    def test_03_churn_predict(self):
        r = self.client.get("/api/v1/churn/predict", params={"top_n": 5})
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertGreater(data["total"], 0)
        self.assertEqual(len(data["risk_distribution"]), 4)
        self.assertLessEqual(len(data["top_risk_users"]), 5)
        self.assertTrue(data["feature_importance"])

    def test_04_churn_recall(self):
        import src.api.main as api_main
        # 重定向 recall 写入到临时库，避免污染真实 retail.db
        tmp_db = os.path.join(self._tmpdir.name, "recall_test.db")
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "CREATE TABLE recall_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_ids TEXT NOT NULL, user_count INTEGER NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'created', "
            "created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')))"
        )
        conn.commit()
        conn.close()
        with patch.object(api_main, "DB_PATH", tmp_db):
            r = self.client.post("/api/v1/churn/recall", json={"user_ids": [10407, 14921]})
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual(data["user_count"], 2)
        self.assertIn("task_id", data)

    def test_05_churn_recall_empty(self):
        r = self.client.post("/api/v1/churn/recall", json={"user_ids": []})
        self.assertEqual(r.status_code, 400)

    def test_06_analyze(self):
        import src.api.main as api_main
        from src.agents.report_store import init_report_table
        # 将来源报告持久化重定向到临时库，避免污染真实 retail.db
        tmp_db = os.path.join(self._tmpdir.name, "report_test.db")
        init_report_table(tmp_db)
        with patch.object(api_main, "DB_PATH", tmp_db):
            r = self.client.post(
                "/api/v1/analyze",
                json={"query": "结合宏观零售数据，给出当前用户流失预警和运营建议", "image_base64": ""},
            )
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["intent"], "综合分析")
        self.assertEqual(d["generation_status"], "fallback")  # client=None → 模板兜底
        self.assertEqual(len(d["sections"]), 6)
        # 模板兜底不伪造结构化建议，应为空数组
        self.assertEqual(d["suggestions"], [])
        # 模板兜底报告不做大模型关键数字覆盖核对，应为 skipped
        self.assertEqual(d["fact_check"]["status"], "skipped")
        # 来源报告持久化：唯一 report_id 且已保存
        self.assertTrue(d["report_id"])
        self.assertTrue(d["report_persisted"])
        # 执行追踪：意图识别 + 工具 + 报告生成
        names = [e["name"] for e in d["execution"]]
        self.assertIn("intent_recognition", names)
        self.assertIn("report_generation", names)
        # 图表数据来自真实工具
        self.assertIn("forecast_values", d["data"]["forecast"])
        self.assertIn("risk_distribution", d["data"]["churn"])
        # 知识库命中片段应作为独立字段返回
        self.assertIn("kb_fragments", d)

    def test_07_analyze_empty_query(self):
        r = self.client.post("/api/v1/analyze", json={"query": "   ", "image_base64": ""})
        self.assertEqual(r.status_code, 400)

    def test_08_overview(self):
        r = self.client.get("/api/v1/overview")
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertGreater(data["latest_macro"]["value"], 0)
        self.assertGreater(data["churn"]["total"], 0)

    def test_09_analyze_report_persist_failure(self):
        """报告持久化失败时，接口仍正常返回报告，并明确标记 report_persisted=False。"""
        import src.api.main as api_main
        with patch.object(api_main, "save_report", side_effect=RuntimeError("db down")):
            r = self.client.post(
                "/api/v1/analyze",
                json={"query": "结合宏观零售数据，给出当前用户流失预警和运营建议", "image_base64": ""},
            )
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["report_persisted"], False)
        self.assertTrue(d["report"])


if __name__ == "__main__":
    unittest.main()
