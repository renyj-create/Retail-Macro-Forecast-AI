# src/tests/test_overview.py
"""
overview 接口健壮性测试。

覆盖：
  1. _finite_float 对 NaN / ±Inf / None / 非数值的处理；
  2. 正常数据返回最新有效记录；
  3. 最新记录无效（1—2 月累计发布口径）时回退到最近一条有效记录；
  4. 全部数据无效时返回明确空态（不伪造 0、不虚构月份）；
  5. 响应可被严格 JSON 序列化，且不含 nan/inf。
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import src.agents.graph_workflow as gw


class TestOverviewRobustness(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # 关闭大模型客户端，避免测试期间调用外部 API
        cls._saved_client = gw.client
        gw.client = None
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._saved_chroma_path = gw.mcp_server.chroma_path
        gw.mcp_server.chroma_path = os.path.join(cls._tmpdir.name, "chroma_db")
        from fastapi.testclient import TestClient
        from src.api.main import app
        cls.client = TestClient(app)
        cls._tmp_db = os.path.join(cls._tmpdir.name, "overview_test.db")

    @classmethod
    def tearDownClass(cls):
        gw.client = cls._saved_client
        gw.mcp_server.chroma_path = cls._saved_chroma_path
        cls._tmpdir.cleanup()

    def _init_db(self):
        """每个用例重建独立表，避免用例间数据相互污染。"""
        conn = sqlite3.connect(self._tmp_db)
        conn.execute("DROP TABLE IF EXISTS macro_retail_sales")
        conn.execute("DROP TABLE IF EXISTS churn_dataset")
        conn.execute(
            "CREATE TABLE macro_retail_sales "
            "(date TEXT, retail_sales_current REAL, yoy_growth REAL)"
        )
        conn.execute("CREATE TABLE churn_dataset (is_churn INTEGER)")
        conn.execute("INSERT INTO churn_dataset VALUES (1)")
        conn.execute("INSERT INTO churn_dataset VALUES (0)")
        conn.commit()
        conn.close()

    def _insert_macro(self, date, value, yoy):
        conn = sqlite3.connect(self._tmp_db)
        conn.execute(
            "INSERT INTO macro_retail_sales VALUES (?, ?, ?)", (date, value, yoy)
        )
        conn.commit()
        conn.close()

    def _get_overview(self):
        import src.api.main as api_main
        with patch.object(api_main, "DB_PATH", self._tmp_db):
            return self.client.get("/api/v1/overview")

    def test_finite_float_handles_invalid(self):
        from src.api.main import _finite_float
        self.assertIsNone(_finite_float(None))
        self.assertIsNone(_finite_float(float("nan")))
        self.assertIsNone(_finite_float(float("inf")))
        self.assertIsNone(_finite_float(float("-inf")))
        self.assertIsNone(_finite_float(""))
        self.assertIsNone(_finite_float("not-a-number"))
        self.assertEqual(_finite_float(39824.4), 39824.4)
        self.assertEqual(_finite_float("0.4"), 0.4)
        self.assertEqual(_finite_float(-1.2), -1.2)

    def test_normal_data_returns_latest_valid(self):
        self._init_db()
        self._insert_macro("2026-07-01 00:00:00", 39022.3, 0.6)
        self._insert_macro("2026-08-01 00:00:00", 39824.4, 0.4)
        r = self._get_overview()
        self.assertEqual(r.status_code, 200)
        lm = r.json()["data"]["latest_macro"]
        self.assertEqual(lm["date"], "2026-08")
        self.assertEqual(lm["value"], 39824.4)
        self.assertEqual(lm["yoy"], 0.4)

    def test_latest_invalid_skips_to_valid(self):
        self._init_db()
        self._insert_macro("2026-07-01 00:00:00", 39022.3, 0.6)
        # 最新记录为「1—2 月累计发布」口径（当月值/同比为空），不应被当作单月数据
        self._insert_macro("2026-08-01 00:00:00", None, None)
        r = self._get_overview()
        self.assertEqual(r.status_code, 200)
        lm = r.json()["data"]["latest_macro"]
        self.assertEqual(lm["date"], "2026-07")
        self.assertEqual(lm["value"], 39022.3)
        self.assertEqual(lm["yoy"], 0.6)

    def test_all_invalid_returns_empty_state(self):
        self._init_db()
        self._insert_macro("2026-08-01 00:00:00", None, None)
        r = self._get_overview()
        self.assertEqual(r.status_code, 200)
        lm = r.json()["data"]["latest_macro"]
        # 不伪造 0 / 不虚构月份：返回明确空态
        self.assertEqual(lm["date"], "")
        self.assertIsNone(lm["value"])
        self.assertIsNone(lm["yoy"])

    def test_response_json_serializable_no_nan_inf(self):
        self._init_db()
        self._insert_macro("2026-08-01 00:00:00", None, None)
        r = self._get_overview()
        self.assertEqual(r.status_code, 200)
        s = r.text.lower()
        self.assertNotIn("nan", s)
        self.assertNotIn("inf", s)
        # 严格序列化不允许 NaN / Infinity（若混入会抛 ValueError）
        json.dumps(r.json(), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
