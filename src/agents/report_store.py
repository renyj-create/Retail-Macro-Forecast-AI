# src/agents/report_store.py
"""
分析报告持久化（最小实现，为待办功能打基础）。

设计说明：
  - 报告目前在 analyze 流程中仅存于内存；本模块提供最小必要的落库能力：
    唯一 report_id + 报告全文 + 结构化建议 + 查询信息 + 创建时间。
  - 采用与 api/main.py 中 feedback / recall_tasks 相同的 SQLite 建表习惯，
    只新增表、不修改或删除既有表与数据。
  - 本阶段不实现待办（todo/action item）的 CRUD。
"""

import json
import sqlite3
import uuid

REPORT_TABLE = "analysis_reports"


def new_report_id() -> str:
    """生成唯一的报告 ID（uuid4 十六进制字符串）。"""
    return uuid.uuid4().hex


def init_report_table(db_path: str) -> None:
    """确保 analysis_reports 表存在（幂等，不覆盖已有数据）。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {REPORT_TABLE} (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                intent TEXT,
                generation_status TEXT,
                fallback_reason TEXT,
                report TEXT,
                suggestions TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_report(db_path: str, report_id: str, query: str, intent: str,
                generation_status: str, fallback_reason: str,
                report: str, suggestions: list) -> None:
    """保存一份分析报告；异常向上抛出，由调用方决定如何记录失败状态。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"""
            INSERT INTO {REPORT_TABLE}
                (id, query, intent, generation_status, fallback_reason, report, suggestions)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                query,
                intent,
                generation_status,
                fallback_reason,
                report,
                json.dumps(suggestions, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()
