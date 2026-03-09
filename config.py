# -*- coding: utf-8 -*-
"""应用升级系统配置（支持 .env 与环境变量）"""
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env(key: str, default: str = "", type_=str):
    val = os.environ.get(key, default).strip()
    if type_ is int:
        try:
            return int(val) if val else int(default) if default else 0
        except ValueError:
            return int(default) if default else 0
    if type_ is bool:
        return val.lower() in ("1", "true", "yes", "on")
    return val or default


# 服务
HOST = _env("HOST", "0.0.0.0")
PORT = _env("PORT", "5000", type_=int)
DEBUG = _env("DEBUG", "true", type_=bool)

# SQLite（空则使用默认路径）
_db = _env("DATABASE", "").strip()
DATABASE = os.path.abspath(_db) if _db else os.path.join(BASE_DIR, "data", "upgrade.db")

# 上传根目录（空则使用默认）
_upload_root = _env("UPLOAD_ROOT", "").strip()
UPLOAD_ROOT = os.path.abspath(_upload_root) if _upload_root else os.path.join(BASE_DIR, "uploads")

# JWT
SECRET_KEY = _env("SECRET_KEY", "upgrade-system-secret-key-change-in-production")
JWT_ALGORITHM = _env("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_DAYS = _env("JWT_EXPIRE_DAYS", "7", type_=int)

# 默认清理：保留最近 N 个月的上传
DEFAULT_CLEANUP_MONTHS = _env("DEFAULT_CLEANUP_MONTHS", "3", type_=int)

# 默认管理员（仅首次初始化数据库时创建，之后改 .env 不影响已有用户）
DEFAULT_ADMIN_USERNAME = _env("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = _env("DEFAULT_ADMIN_PASSWORD", "admin123")

# API Token：用于 curl 等脚本直传升级包，留空则禁用 /api/upload-by-token
API_TOKEN = _env("API_TOKEN", "").strip()

# 允许的扩展名
JAR_EXT = ".jar"
DIST_ZIP_EXT = ".zip"
DIST_ZIP_NAME = "dist.zip"
