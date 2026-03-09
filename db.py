# -*- coding: utf-8 -*-
"""SQLite 数据库初始化与模型"""
import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager

import config

def get_conn():
    os.makedirs(os.path.dirname(config.DATABASE) or ".", exist_ok=True)
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        c = conn.cursor()
        # 用户表：role=admin|user，disabled=0 正常 1 禁用
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                disabled INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col, default in (("role", "user"), ("disabled", 0)):
            try:
                c.execute("ALTER TABLE users ADD COLUMN " + col + (" INTEGER NOT NULL DEFAULT 0" if col == "disabled" else " TEXT NOT NULL DEFAULT 'user'"))
            except sqlite3.OperationalError:
                pass
        # 上传路径配置（旧表，保留兼容）
        c.execute("""
            CREATE TABLE IF NOT EXISTS upload_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path_type TEXT NOT NULL,
                target_path TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(path_type)
            )
        """)
        # 上传配置表：配置名、上传路径、上传后操作、当前版本号（如 V1.0，上传后自动小版本+1）
        c.execute("""
            CREATE TABLE IF NOT EXISTS upload_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                target_path TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT 'copy',
                description TEXT,
                current_version TEXT DEFAULT 'V1.0',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            c.execute("ALTER TABLE upload_config ADD COLUMN current_version TEXT DEFAULT 'V1.0'")
        except sqlite3.OperationalError:
            pass
        # 上传历史（version_seq 按上传配置自增）
        c.execute("""
            CREATE TABLE IF NOT EXISTS upload_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER,
                upload_path_config_id INTEGER,
                version_seq INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        try:
            c.execute("ALTER TABLE upload_history ADD COLUMN version_seq INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE upload_history ADD COLUMN version_str TEXT")
        except sqlite3.OperationalError:
            pass
        # 版本表：按配置 + 包名区分版本，字段 配置名(关联)、包名、版本号、最后更新时间
        c.execute("""
            CREATE TABLE IF NOT EXISTS package_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id INTEGER NOT NULL,
                package_name TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT 'V1.0',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(config_id, package_name),
                FOREIGN KEY (config_id) REFERENCES upload_config(id)
            )
        """)
        # 清理配置：保留最近 N 个月
        c.execute("""
            CREATE TABLE IF NOT EXISTS cleanup_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keep_months INTEGER NOT NULL DEFAULT 3,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 默认清理配置
        c.execute("SELECT 1 FROM cleanup_config LIMIT 1")
        if c.fetchone() is None:
            c.execute(
                "INSERT INTO cleanup_config (keep_months) VALUES (?)",
                (config.DEFAULT_CLEANUP_MONTHS,)
            )
        # 默认上传路径（若不存在）
        c.execute("SELECT 1 FROM upload_paths WHERE path_type = 'jar' LIMIT 1")
        if c.fetchone() is None:
            c.execute(
                "INSERT INTO upload_paths (path_type, target_path, description) VALUES (?, ?, ?)",
                ("jar", "jar", "JAR 文件上传目录")
            )
        c.execute("SELECT 1 FROM upload_paths WHERE path_type = 'dist_zip' LIMIT 1")
        if c.fetchone() is None:
            c.execute(
                "INSERT INTO upload_paths (path_type, target_path, description) VALUES (?, ?, ?)",
                ("dist_zip", "dist", "dist.zip 解压目录")
            )
        # 默认上传配置（若表为空）
        c.execute("SELECT 1 FROM upload_config LIMIT 1")
        if c.fetchone() is None:
            c.execute(
                "INSERT INTO upload_config (name, target_path, action, description) VALUES (?, ?, ?, ?)",
                ("JAR 文件", "jar", "copy", "仅复制，适用于 .jar 等")
            )
            c.execute(
                "INSERT INTO upload_config (name, target_path, action, description) VALUES (?, ?, ?, ?)",
                ("ZIP 解压", "dist", "unzip", "上传后 unzip 解压，适用于 .zip")
            )
            c.execute(
                "INSERT INTO upload_config (name, target_path, action, description) VALUES (?, ?, ?, ?)",
                ("TAR 解压", "dist", "tar", "上传后 tar 解压，适用于 .tar / .tar.gz")
            )
        # 默认管理员（仅当无用户时，账号密码来自 config / .env）
        c.execute("SELECT 1 FROM users LIMIT 1")
        if c.fetchone() is None:
            import hashlib
            h = hashlib.sha256((config.DEFAULT_ADMIN_PASSWORD + config.SECRET_KEY).encode()).hexdigest()
            c.execute(
                "INSERT INTO users (username, password_hash, role, disabled) VALUES (?, ?, 'admin', 0)",
                (config.DEFAULT_ADMIN_USERNAME, h)
            )
        # 已有用户但无 role：设为 admin，无 disabled：设为 0
        try:
            c.execute("UPDATE users SET role = 'admin' WHERE role IS NULL OR role = ''")
            c.execute("UPDATE users SET disabled = 0 WHERE disabled IS NULL")
        except sqlite3.OperationalError:
            pass


def dict_from_row(row):
    if row is None:
        return None
    return dict(zip(row.keys(), row))
