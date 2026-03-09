# -*- coding: utf-8 -*-
"""文件上传：先保存原始文件到 uploads/YYYYMMDD/HHMM-uuid/，再按配置执行 仅复制 / unzip / tar 解压"""
import os
import re
import zipfile
import tarfile
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import config
from db import get_db, dict_from_row

# 版本号格式：V<major>.<minor>，上传后仅递增小版本
VERSION_PATTERN = re.compile(r"^V?(\d+)\.(\d+)$", re.IGNORECASE)
DEFAULT_VERSION = "V1.0"

# 上传后操作
ACTION_COPY = "copy"
ACTION_UNZIP = "unzip"
ACTION_TAR = "tar"
ACTIONS = (ACTION_COPY, ACTION_UNZIP, ACTION_TAR)


def _resolve_upload_root():
    return os.path.abspath(config.UPLOAD_ROOT)


def _resolve_target_dir(target_path: str):
    """将配置中的 target_path 解析为绝对目录。"""
    target = (target_path or "").strip()
    if not target:
        return None
    root = _resolve_upload_root()
    if os.path.isabs(target):
        return target
    return os.path.join(root, target)


def _make_staging_dir():
    """生成并创建本次上传的原始数据目录：uploads/YYYYMMDD/HHMM-uuid/，返回绝对路径。"""
    root = _resolve_upload_root()
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M")
    short_uuid = uuid.uuid4().hex[:8]
    staging_dir = os.path.join(root, date_str, f"{time_str}-{short_uuid}")
    os.makedirs(staging_dir, exist_ok=True)
    return staging_dir


# ---------- 上传配置表（新） ----------


def _parse_version(s: str):
    """解析版本号 V1.0 / 1.0 -> (major, minor)，无法解析返回 (1, 0)。"""
    if not s or not s.strip():
        return 1, 0
    s = s.strip().upper()
    if not s.startswith("V"):
        s = "V" + s
    m = VERSION_PATTERN.match(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1, 0


def _format_version(major: int, minor: int) -> str:
    return f"V{major}.{minor}"


def next_minor_version(current_version: str) -> str:
    """在当前版本基础上仅递增小版本，如 V1.0 -> V1.1。"""
    major, minor = _parse_version(current_version or "")
    return _format_version(major, minor + 1)


def set_config_current_version(config_id: int, version_str: str) -> bool:
    """更新配置的当前版本号（支持手动修改后在此基础上再递增）。"""
    version_str = (version_str or "").strip() or DEFAULT_VERSION
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE upload_config SET current_version = ? WHERE id = ?", (version_str, config_id))
        return c.rowcount > 0


# ---------- 版本表：按配置 + 包名（文件名去后缀）区分版本 ----------


def _package_name_from_filename(filename: str) -> str:
    """从文件名得到包名，用于区分不同版本线。如 2_副本.jar -> 2_副本。"""
    if not filename or not filename.strip():
        return ""
    base = os.path.splitext(filename.strip())[0]
    return base or filename.strip()


def get_next_version_for_package(config_id: int, package_name: str) -> str:
    """
    版本更新时优先从版本表取数据；若版本表没有该 (config_id, package_name) 则新增一条 V1.0。
    返回本次应使用的版本号（新记录为 V1.0，已有记录为当前版本+1 并写回表）。
    """
    package_name = (package_name or "").strip()
    if not package_name:
        return DEFAULT_VERSION
    config_id = int(config_id)
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT version FROM package_version WHERE config_id = ? AND package_name = ?",
            (config_id, package_name),
        )
        row = c.fetchone()
        if row is None:
            c.execute(
                "INSERT INTO package_version (config_id, package_name, version, updated_at) VALUES (?, ?, ?, datetime('now'))",
                (config_id, package_name, DEFAULT_VERSION),
            )
            return DEFAULT_VERSION
        current = (row[0] or "").strip() or DEFAULT_VERSION
        next_ver = next_minor_version(current)
        c.execute(
            "UPDATE package_version SET version = ?, updated_at = datetime('now') WHERE config_id = ? AND package_name = ?",
            (next_ver, config_id, package_name),
        )
        return next_ver


def list_package_versions():
    """版本表列表：配置名、包名、版本号、最后更新时间。"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT pv.id, pv.config_id, pv.package_name, pv.version, pv.updated_at, uc.name AS config_name
               FROM package_version pv
               LEFT JOIN upload_config uc ON pv.config_id = uc.id
               ORDER BY pv.updated_at DESC, pv.config_id, pv.package_name"""
        )
        rows = c.fetchall()
    out = []
    for r in rows:
        d = dict_from_row(r)
        out.append({
            "id": d.get("id"),
            "config_id": d.get("config_id"),
            "config_name": d.get("config_name") or "",
            "package_name": d.get("package_name") or "",
            "version": (d.get("version") or "").strip() or DEFAULT_VERSION,
            "updated_at": d.get("updated_at"),
        })
    return out


def list_upload_configs():
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, name, target_path, action, description, current_version, created_at FROM upload_config ORDER BY id"
        )
        rows = c.fetchall()
    out = [dict_from_row(r) for r in rows]
    for row in out:
        if row.get("current_version") is None:
            row["current_version"] = DEFAULT_VERSION
    return out


def get_upload_config(config_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, name, target_path, action, description, current_version, created_at FROM upload_config WHERE id = ?",
            (config_id,),
        )
        row = c.fetchone()
    if not row:
        return None
    d = dict_from_row(row)
    if d.get("current_version") is None:
        d["current_version"] = DEFAULT_VERSION
    return d


def create_upload_config(
    name: str, target_path: str, action: str, description: str = "", current_version: str = ""
):
    if action not in ACTIONS:
        return None, "action 须为 copy / unzip / tar"
    name = (name or "").strip()
    target_path = (target_path or "").strip()
    if not name or not target_path:
        return None, "配置名和上传路径不能为空"
    version = (current_version or "").strip() or DEFAULT_VERSION
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO upload_config (name, target_path, action, description, current_version) VALUES (?, ?, ?, ?, ?)",
            (name, target_path, action, description or "", version),
        )
        return c.lastrowid, None


def update_upload_config(
    config_id: int, name: str, target_path: str, action: str, description: str = "", current_version: str = ""
):
    if action not in ACTIONS:
        return "action 须为 copy / unzip / tar"
    name = (name or "").strip()
    target_path = (target_path or "").strip()
    if not name or not target_path:
        return "配置名和上传路径不能为空"
    version = (current_version or "").strip()
    with get_db() as conn:
        c = conn.cursor()
        if version:
            c.execute(
                "UPDATE upload_config SET name=?, target_path=?, action=?, description=?, current_version=? WHERE id=?",
                (name, target_path, action, description or "", version, config_id),
            )
        else:
            c.execute(
                "UPDATE upload_config SET name=?, target_path=?, action=?, description=? WHERE id=?",
                (name, target_path, action, description or "", config_id),
            )
        return None if c.rowcount else "记录不存在"


def delete_upload_config(config_id: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM upload_config WHERE id = ?", (config_id,))
        return c.rowcount > 0


# ---------- 按配置上传 ----------


def save_by_config(config_id: int, file_storage, user_id: int) -> tuple:
    """
    1) 先将上传的原始文件保存到 uploads/YYYYMMDD/HHMM-uuid/ 目录；
    2) 再按配置执行：copy 复制到目标目录 / unzip 或 tar 解压到目标目录。
    返回 (原始文件路径即 staging 路径, 错误信息, version_seq)，失败时 version_seq=0。
    """
    if not file_storage or not file_storage.filename:
        return None, "未选择文件", 0, None
    cfg = get_upload_config(config_id)
    if not cfg:
        return None, "上传配置不存在", 0, None
    action = (cfg.get("action") or ACTION_COPY).lower()
    if action not in ACTIONS:
        return None, "不支持的操作: " + action, 0, None
    target_dir = _resolve_target_dir(cfg["target_path"])
    if not target_dir:
        return None, "上传路径无效", 0, None
    os.makedirs(target_dir, exist_ok=True)

    name = file_storage.filename
    # 1) 原始数据保存到 uploads/YYYYMMDD/HHMM-uuid/
    staging_dir = _make_staging_dir()
    staging_path = os.path.join(staging_dir, name)
    try:
        file_storage.save(staging_path)
    except Exception as e:
        return None, str(e), 0, None
    size = os.path.getsize(staging_path)

    # 2) 按文件名得到包名，从版本表取/写版本号（无则新增 V1.0）
    package_name = _package_name_from_filename(name)
    next_ver = get_next_version_for_package(config_id, package_name)

    # 3) 按配置执行
    if action == ACTION_COPY:
        try:
            shutil.copy2(staging_path, os.path.join(target_dir, name))
        except Exception as e:
            return None, "复制到目标目录失败: " + str(e), 0, None
        version_seq = _append_history(user_id, name, staging_path, "copy", size, config_id, version_str=next_ver)
        return staging_path, None, version_seq, next_ver

    if action == ACTION_UNZIP:
        if not name.lower().endswith(".zip"):
            return None, "该配置需上传 .zip 文件", 0, None
        try:
            with zipfile.ZipFile(staging_path, "r") as zf:
                zf.extractall(target_dir)
        except Exception as e:
            return None, "解压失败: " + str(e), 0, None
        version_seq = _append_history(user_id, name, staging_path, "unzip", size, config_id, version_str=next_ver)
        return staging_path, None, version_seq, next_ver

    if action == ACTION_TAR:
        lower = name.lower()
        if not (lower.endswith(".tar") or lower.endswith(".tar.gz") or lower.endswith(".tgz")):
            return None, "该配置需上传 .tar / .tar.gz / .tgz 文件", 0, None
        try:
            with tarfile.open(staging_path, "r:*") as tf:
                tf.extractall(target_dir)
        except Exception as e:
            return None, "解压失败: " + str(e), 0, None
        version_seq = _append_history(user_id, name, staging_path, "tar", size, config_id, version_str=next_ver)
        return staging_path, None, version_seq, next_ver

    return None, "不支持的操作", 0, None


def _next_version_seq(conn, config_id: int) -> int:
    """按上传配置生成下一个版本序号（自增）。"""
    c = conn.cursor()
    c.execute(
        "SELECT COALESCE(MAX(version_seq), 0) + 1 FROM upload_history WHERE upload_path_config_id = ?",
        (config_id,),
    )
    row = c.fetchone()
    return row[0] if row else 1


def _append_history(
    user_id: int,
    file_name: str,
    file_path: str,
    file_type: str,
    file_size: int,
    config_id: int,
    version_str: str = None,
) -> int:
    """写入上传历史；当 config_id > 0 时写入 version_seq；version_str 为版本表分配的版本号（可选）。"""
    with get_db() as conn:
        c = conn.cursor()
        version_seq = None
        if config_id and int(config_id) > 0:
            version_seq = _next_version_seq(conn, int(config_id))
        c.execute(
            """INSERT INTO upload_history (user_id, file_name, file_path, file_type, file_size, upload_path_config_id, version_seq, version_str)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, file_name, file_path, file_type, file_size, config_id, version_seq, (version_str or "").strip() or None),
        )
        return version_seq or 0


# ---------- 兼容旧接口（按类型推断配置） ----------


def get_path_config(path_type: str):
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, path_type, target_path, description FROM upload_paths WHERE path_type = ?",
            (path_type,),
        )
        row = c.fetchone()
    return dict_from_row(row) if row else None


def get_absolute_target_dir(path_type: str):
    cfg = get_path_config(path_type)
    if not cfg:
        return None
    return _resolve_target_dir(cfg["target_path"])


def save_jar(file_storage, user_id: int) -> tuple:
    """兼容：保存 .jar 到 jar 配置目录。"""
    cfg = get_upload_config_by_action_path("copy", "jar")
    if cfg:
        return save_by_config(cfg["id"], file_storage, user_id)
    if not file_storage or not file_storage.filename or not file_storage.filename.lower().endswith(".jar"):
        return None, "仅支持 .jar 文件"
    target_dir = get_absolute_target_dir("jar")
    if not target_dir:
        return None, "未配置 JAR 上传路径"
    os.makedirs(target_dir, exist_ok=True)
    name = file_storage.filename
    dest = os.path.join(target_dir, name)
    try:
        file_storage.save(dest)
    except Exception as e:
        return None, str(e)
    size = os.path.getsize(dest)
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM upload_paths WHERE path_type = 'jar' LIMIT 1")
        row = c.fetchone()
        path_id = row[0] if row else None
        _append_history(user_id, name, dest, "jar", size, path_id or 0)
    return dest, None


def get_upload_config_by_action_path(action: str, target_path_sub: str):
    for c in list_upload_configs():
        if (c.get("action") == action) and (target_path_sub in (c.get("target_path") or "")):
            return c
    return None


def save_dist_zip(file_storage, user_id: int) -> tuple:
    """兼容：zip 解压到 dist 配置。"""
    cfg = get_upload_config_by_action_path("unzip", "dist") or get_upload_config_by_action_path("unzip", "")
    if cfg:
        return save_by_config(cfg["id"], file_storage, user_id)
    if not file_storage or not file_storage.filename or not file_storage.filename.lower().endswith(".zip"):
        return None, "仅支持 .zip 文件"
    target_dir = get_absolute_target_dir("dist_zip")
    if not target_dir:
        return None, "未配置 dist.zip 上传路径"
    os.makedirs(target_dir, exist_ok=True)
    name = file_storage.filename
    zip_path = os.path.join(target_dir, name)
    try:
        file_storage.save(zip_path)
    except Exception as e:
        return None, str(e)
    size = os.path.getsize(zip_path)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target_dir)
    except Exception as e:
        if os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass
        return None, "解压失败: " + str(e)
    try:
        os.remove(zip_path)
    except Exception:
        pass
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM upload_paths WHERE path_type = 'dist_zip' LIMIT 1")
        row = c.fetchone()
        path_id = row[0] if row else None
        _append_history(user_id, name, target_dir, "dist_zip", size, path_id or 0)
    return target_dir, None


def list_history(user_id: int = None, limit: int = 500):
    with get_db() as conn:
        c = conn.cursor()
        if user_id is not None:
            c.execute(
                """SELECT h.id, h.file_name, h.file_path, h.file_type, h.file_size, h.version_seq, h.version_str, h.created_at, u.username
                   FROM upload_history h
                   LEFT JOIN users u ON h.user_id = u.id
                   WHERE h.user_id = ?
                   ORDER BY h.created_at DESC LIMIT ?""",
                (user_id, limit),
            )
        else:
            c.execute(
                """SELECT h.id, h.file_name, h.file_path, h.file_type, h.file_size, h.version_seq, h.version_str, h.created_at, u.username
                   FROM upload_history h
                   LEFT JOIN users u ON h.user_id = u.id
                   ORDER BY h.created_at DESC LIMIT ?""",
                (limit,),
            )
        rows = c.fetchall()
    return [dict_from_row(r) for r in rows]


def get_history_item(history_id: int, user_id: int = None):
    with get_db() as conn:
        c = conn.cursor()
        if user_id is not None:
            c.execute(
                "SELECT * FROM upload_history WHERE id = ? AND user_id = ?",
                (history_id, user_id),
            )
        else:
            c.execute("SELECT * FROM upload_history WHERE id = ?", (history_id,))
        row = c.fetchone()
    return dict_from_row(row) if row else None


def get_file_path_for_download(history_id: int, user_id: int = None) -> tuple:
    """返回 (本地绝对路径, 下载文件名) 或 (None, 错误信息)。"""
    item = get_history_item(history_id, user_id)
    if not item:
        return None, "记录不存在"
    path = item["file_path"]
    name = item["file_name"]
    ft = item.get("file_type") or ""
    if ft in ("dist_zip", "unzip", "tar"):
        if os.path.isdir(path):
            return None, "该记录为解压目录，不支持直接下载"
        if os.path.isfile(path):
            return path, name
        return None, "文件已不存在"
    if os.path.isfile(path):
        return path, name
    return None, "文件已不存在"
