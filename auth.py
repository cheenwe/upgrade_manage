# -*- coding: utf-8 -*-
"""登录与 JWT"""
import hashlib
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import request, jsonify

import config
from db import get_db, dict_from_row


def hash_password(password: str) -> str:
    return hashlib.sha256((password + config.SECRET_KEY).encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def create_token(user_id: int, username: str, role: str = "user") -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=config.JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    except Exception:
        return None


def login_user(username: str, password: str):
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, username, password_hash, role, disabled FROM users WHERE username = ?",
            (username,),
        )
        row = c.fetchone()
    if not row:
        return None, "用户不存在"
    user = dict_from_row(row)
    if user.get("disabled"):
        return None, "账号已禁用"
    if not verify_password(password, user["password_hash"]):
        return None, "密码错误"
    role = (user.get("role") or "user").strip().lower()
    if role != "admin":
        role = "user"
    token = create_token(user["id"], user["username"], role)
    return {
        "user_id": user["id"],
        "username": user["username"],
        "token": token,
        "role": role,
        "is_admin": role == "admin",
    }, None


def require_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        auth = request.headers.get("Authorization")
        token = None
        if auth and auth.startswith("Bearer "):
            token = auth[7:]
        if not token:
            token = request.values.get("token") or (request.get_json(silent=True) or {}).get("token")
        if not token:
            return jsonify({"success": 0, "msg": "请先登录"}), 401
        payload = decode_token(token)
        if not payload:
            return jsonify({"success": 0, "msg": "登录已过期，请重新登录"}), 401
        request.current_user = payload
        return f(*args, **kwargs)
    return wrapped


def require_admin(f):
    """仅管理员可访问（依赖 require_auth 已注入 current_user）。"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if (getattr(request, "current_user", None) or {}).get("role") != "admin":
            return jsonify({"success": 0, "msg": "仅管理员可操作"}), 403
        return f(*args, **kwargs)
    return wrapped


# ---------- 用户管理（仅管理员调用前应在路由中加 require_admin） ----------


def list_users():
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, username, role, disabled, created_at FROM users ORDER BY id"
        )
        rows = c.fetchall()
    return [dict_from_row(r) for r in rows]


def get_user_by_id(uid: int):
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, username, role, disabled, created_at FROM users WHERE id = ?",
            (uid,),
        )
        row = c.fetchone()
    return dict_from_row(row) if row else None


def get_user_by_username(username: str, exclude_id: int = None):
    with get_db() as conn:
        c = conn.cursor()
        if exclude_id is not None:
            c.execute("SELECT id FROM users WHERE username = ? AND id != ?", (username, exclude_id))
        else:
            c.execute("SELECT id FROM users WHERE username = ?", (username,))
        return c.fetchone() is not None


def create_user(username: str, password: str, role: str = "user"):
    username = (username or "").strip()
    if len(username) < 3:
        return None, "用户名至少 3 位"
    if not password or len(password) < 5:
        return None, "密码至少 5 位"
    role = (role or "user").strip().lower()
    if role != "admin":
        role = "user"
    if get_user_by_username(username):
        return None, "用户名已存在"
    pw_hash = hash_password(password)
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (username, password_hash, role, disabled) VALUES (?, ?, ?, 0)",
            (username, pw_hash, role),
        )
        uid = c.lastrowid
    return uid, None


def update_user(uid: int, username: str, role: str):
    user = get_user_by_id(uid)
    if not user:
        return "用户不存在"
    username = (username or "").strip()
    if len(username) < 3:
        return "用户名至少 3 位"
    role = (role or "user").strip().lower()
    if role != "admin":
        role = "user"
    if get_user_by_username(username, exclude_id=uid):
        return "用户名已存在"
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET username = ?, role = ? WHERE id = ?", (username, role, uid))
    return None


def set_user_disabled(uid: int, disabled: bool):
    user = get_user_by_id(uid)
    if not user:
        return "用户不存在"
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET disabled = ? WHERE id = ?", (1 if disabled else 0, uid))
    return None


def set_user_password(uid: int, new_password: str):
    if not new_password or len(new_password) < 5:
        return "密码至少 5 位"
    user = get_user_by_id(uid)
    if not user:
        return "用户不存在"
    pw_hash = hash_password(new_password)
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, uid))
    return None


def delete_user(uid: int, current_uid: int):
    if uid == current_uid:
        return "不能删除自己"
    user = get_user_by_id(uid)
    if not user:
        return "用户不存在"
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id = ?", (uid,))
    return None
