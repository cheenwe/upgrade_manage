# -*- coding: utf-8 -*-
"""自动清理：按配置删除 N 个月前的上传文件及历史记录"""
from datetime import datetime, timedelta

from db import get_db, dict_from_row


def get_cleanup_config():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, keep_months, updated_at FROM cleanup_config ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
    return dict_from_row(row) if row else None


def set_cleanup_config(keep_months: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM cleanup_config LIMIT 1")
        row = c.fetchone()
        if row:
            c.execute(
                "UPDATE cleanup_config SET keep_months = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (keep_months, row[0])
            )
        else:
            c.execute(
                "INSERT INTO cleanup_config (keep_months) VALUES (?)",
                (keep_months,)
            )


def run_cleanup() -> tuple:
    """执行清理。返回 (删除的历史条数, 错误信息)。"""
    import os
    cfg = get_cleanup_config()
    if not cfg or cfg["keep_months"] < 1:
        return 0, None
    keep_months = cfg["keep_months"]
    before = datetime.utcnow() - timedelta(days=keep_months * 30)
    before_ts = before.strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, file_path, file_type FROM upload_history WHERE created_at < ?",
            (before_ts,)
        )
        rows = c.fetchall()
    ids_to_delete = []
    for row in rows:
        hid, file_path, file_type = row["id"], row["file_path"], row["file_type"]
        try:
            if file_path and os.path.isfile(file_path):
                os.remove(file_path)
        except Exception:
            pass
        ids_to_delete.append(hid)
    if not ids_to_delete:
        return 0, None
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM upload_history WHERE id IN ({})".format(",".join("?" * len(ids_to_delete))), ids_to_delete)
        deleted = c.rowcount
    return deleted, None
