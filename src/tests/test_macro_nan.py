# src/tests/test_macro_nan.py
"""
宏观查询 NaN / 无穷值回归测试。

覆盖：
  1. _finite_float 对 NaN / ±Inf / None / 非数值的明确处理；
  2. query_macro_sqlite 剔除「1—2 月累计发布」口径的缺失行（如 2026-02），
     返回文本不含 nan/inf，payload 中不存在 NaN 或无穷值；
  3. 有效月份与同比统计符合单月口径；
  4. 全部记录无效时工具稳定返回「暂无有效数据」，不崩溃、不伪造数字。
"""
import os
import sys
import json
import math
import shutil
import sqlite3
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from src.agents.tools import MCPToolServer, _finite_float


class TestFiniteFloat(unittest.TestCase):
    """_finite_float 明确处理各类非有限数值。"""

    def test_nan_inf_none_non_numeric(self):
        self.assertIsNone(_finite_float(float('nan')))
        self.assertIsNone(_finite_float(float('inf')))
        self.assertIsNone(_finite_float(float('-inf')))
        self.assertIsNone(_finite_float(None))
        self.assertIsNone(_finite_float(''))
        self.assertIsNone(_finite_float('not-a-number'))

    def test_valid_numbers(self):
        self.assertEqual(_finite_float(39824.4), 39824.4)
        self.assertEqual(_finite_float('0.4'), 0.4)
        self.assertEqual(_finite_float(-1.2), -1.2)


class TestQueryMacroNan(unittest.TestCase):

    def setUp(self):
        self.mcp_server = MCPToolServer()
        self.test_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.test_dir, "test_retail.db")
        self.mcp_server.db_path = self.test_db_path

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _create_table(self):
        conn = sqlite3.connect(self.test_db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS macro_retail_sales (
                date TEXT, retail_sales_current REAL, yoy_growth REAL
            )
        """)
        conn.commit()
        conn.close()

    def test_filters_cumulative_missing_rows(self):
        """2026-02 这类累计口径缺失行应被剔除，其余有效历史数据保留。"""
        self._create_table()
        conn = sqlite3.connect(self.test_db_path)
        conn.execute("INSERT INTO macro_retail_sales VALUES ('2026-08-01', 39824.4, 0.4)")
        conn.execute("INSERT INTO macro_retail_sales VALUES ('2026-07-01', 39022.3, 0.6)")
        # 累计口径缺失行：当月值与同比均为空（1—2 月合并发布）
        conn.execute("INSERT INTO macro_retail_sales VALUES ('2026-02-01', NULL, NULL)")
        conn.execute("INSERT INTO macro_retail_sales VALUES ('2026-01-01', 35000.0, -1.2)")
        conn.commit()
        conn.close()

        text, payload = self.mcp_server.query_macro_sqlite(limit=12)

        # 返回文本与 payload 均不得包含 nan / inf
        lowered = text.lower()
        self.assertNotIn('nan', lowered)
        self.assertNotIn('inf', lowered)
        json.dumps(payload, allow_nan=False)  # 若含 NaN/Inf 会抛 ValueError

        # 有效月份：2026-02 被剔除，其余 3 个月保留且最新在前
        self.assertEqual(len(payload), 3)
        self.assertEqual([p['date'] for p in payload], ['2026-08', '2026-07', '2026-01'])
        self.assertNotIn('2026-02', text)

        # 最新一期数值与同比符合现有单月口径
        self.assertEqual(payload[0]['value'], 39824.4)
        self.assertEqual(payload[0]['yoy'], 0.4)

        # 同比区间统计不被 NaN 污染
        yoy_values = [p['yoy'] for p in payload]
        self.assertTrue(all(math.isfinite(v) for v in yoy_values))
        self.assertEqual(min(yoy_values), -1.2)
        self.assertEqual(max(yoy_values), 0.6)

    def test_all_records_invalid_returns_no_data(self):
        """全部记录无效时应稳定返回「暂无有效数据」，不崩溃、不伪造数字。"""
        self._create_table()
        conn = sqlite3.connect(self.test_db_path)
        conn.execute("INSERT INTO macro_retail_sales VALUES ('2026-02-01', NULL, NULL)")
        conn.commit()
        conn.close()

        text, payload = self.mcp_server.query_macro_sqlite(limit=12)

        self.assertIn('暂无', text)
        self.assertNotIn('nan', text.lower())
        self.assertNotIn('inf', text.lower())
        self.assertEqual(payload, [])
        json.dumps(payload, allow_nan=False)

        # 执行追踪仍记录为 success，且 summary 明确说明无有效数据
        rec = self.mcp_server._execution_summary('query_macro_sqlite')
        self.assertEqual(rec['status'], 'success')
        self.assertIn('暂无', rec['summary'])


if __name__ == '__main__':
    unittest.main()
