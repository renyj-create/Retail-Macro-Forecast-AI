# src/tests/test_report_store.py
"""
报告持久化测试：report_id 唯一性、建表幂等、保存可读、不影响既有表与数据。
全部使用临时数据库，不触碰真实 retail.db。
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from src.agents.report_store import (
    REPORT_TABLE,
    init_report_table,
    save_report,
    new_report_id,
)


class TestReportStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "test.db")

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def test_new_report_id_is_unique(self):
        ids = {new_report_id() for _ in range(1000)}
        self.assertEqual(len(ids), 1000)

    def test_init_report_table_is_idempotent(self):
        init_report_table(self.db_path)
        init_report_table(self.db_path)  # 重复执行不报错、不丢数据
        conn = self._connect()
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (REPORT_TABLE,)
        )]
        conn.close()
        self.assertEqual(names, [REPORT_TABLE])

    def test_save_report_persists_row(self):
        init_report_table(self.db_path)
        rid = new_report_id()
        save_report(
            self.db_path, rid, "分析宏观社零趋势", "宏观分析",
            "success", "", "===== 报告 =====\n...", [{"title": "关注高流失用户"}],
        )
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {REPORT_TABLE} WHERE id = ?", (rid,)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["query"], "分析宏观社零趋势")
        self.assertEqual(row["intent"], "宏观分析")
        self.assertEqual(row["generation_status"], "success")
        self.assertEqual(json.loads(row["suggestions"]), [{"title": "关注高流失用户"}])
        self.assertTrue(row["created_at"])

    def test_init_does_not_touch_existing_tables(self):
        # 预置既有表与数据
        conn = self._connect()
        conn.execute("CREATE TABLE feedback (id INTEGER PRIMARY KEY, query TEXT)")
        conn.execute("CREATE TABLE recall_tasks (id INTEGER PRIMARY KEY, user_ids TEXT)")
        conn.execute("INSERT INTO feedback (query) VALUES ('旧反馈')")
        conn.execute("INSERT INTO recall_tasks (user_ids) VALUES ('[1,2]')")
        conn.commit()
        conn.close()

        init_report_table(self.db_path)
        save_report(self.db_path, new_report_id(), "q", "intent", "success", "", "r", [])

        conn = self._connect()
        feedback_rows = conn.execute("SELECT query FROM feedback").fetchall()
        recall_rows = conn.execute("SELECT user_ids FROM recall_tasks").fetchall()
        conn.close()
        self.assertEqual(feedback_rows, [("旧反馈",)])
        self.assertEqual(recall_rows, [("[1,2]",)])


if __name__ == "__main__":
    unittest.main()
