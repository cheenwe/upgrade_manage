# -*- coding: utf-8 -*-
"""应用升级系统 - Flask 主入口"""
import os

from flask import Flask, request, jsonify, send_file, abort
from flask_cors import CORS

import config
from db import init_db, get_db, dict_from_row
from auth import (
    login_user,
    require_auth,
    require_admin,
    list_users,
    get_user_by_id,
    create_user,
    update_user,
    set_user_disabled,
    set_user_password,
    delete_user,
)
from upload_handler import (
    save_jar,
    save_dist_zip,
    save_by_config,
    list_upload_configs,
    get_upload_config,
    create_upload_config,
    update_upload_config,
    delete_upload_config,
    list_history,
    get_history_item,
    get_file_path_for_download,
    get_path_config,
    get_absolute_target_dir,
    list_package_versions,
)
from cleanup import get_cleanup_config, set_cleanup_config, run_cleanup

# web 目录作为静态资源根目录，所有前端页面与静态文件均由此提供
app = Flask(__name__, static_folder="web", static_url_path="")
CORS(app, supports_credentials=True)


@app.route("/")
def index():
    """首页：返回 web/index.html"""
    return app.send_static_file("index.html")


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or len(username) < 3:
        return jsonify({"success": 0, "msg": "用户名至少 3 位"})
    if not password or len(password) < 5:
        return jsonify({"success": 0, "msg": "密码至少 5 位"})
    result, err = login_user(username, password)
    if err:
        return jsonify({"success": 0, "msg": err})
    return jsonify({
        "success": 1,
        "msg": "登录成功",
        "token": result["token"],
        "username": result["username"],
        "is_admin": result.get("is_admin", False),
    })


@app.route("/api/me", methods=["GET"])
@require_auth
def api_me():
    """当前用户信息，用于前端根据 is_admin 显示/隐藏管理员菜单。"""
    u = request.current_user
    return jsonify({
        "success": 1,
        "username": u.get("username"),
        "is_admin": u.get("role") == "admin",
    })


def _do_upload_legacy(f, user_id):
    """兼容：未传 config_id 时按扩展名走旧逻辑。"""
    if not f or not f.filename:
        return None, "未选择文件"
    name = f.filename.lower()
    if name.endswith(".jar"):
        return save_jar(f, user_id)
    if name.endswith(".zip"):
        return save_dist_zip(f, user_id)
    return None, "仅支持 .jar 或 .zip 文件，或请选择上传配置"


@app.route("/api/uploads", methods=["POST"])
@require_auth
def api_uploads():
    """统一上传：传 config_id 时按配置表执行（copy/unzip/tar），否则兼容旧逻辑。"""
    f = request.files.get("file") or request.files.get("filepond")
    config_id = request.form.get("config_id") or request.values.get("config_id")
    if config_id is not None:
        try:
            config_id = int(config_id)
        except (TypeError, ValueError):
            config_id = None
    if config_id is not None:
        result = save_by_config(config_id, f, request.current_user["user_id"])
        path, err = result[0], result[1]
        version_seq = result[2] if len(result) > 2 else 0
        version_str = result[3] if len(result) > 3 else None
    else:
        path, err = _do_upload_legacy(f, request.current_user["user_id"])
        version_seq = 0
        version_str = None
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    out = {"success": 1, "msg": "上传成功", "data": path}
    if version_seq:
        out["version_seq"] = version_seq
    if version_str:
        out["version"] = version_str
    return jsonify(out)


def _get_api_token_from_request():
    """从请求中读取 API Token：Header Authorization: Bearer <token> 或 表单/查询参数 api_token。"""
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return auth[7:].strip()
    return (request.form.get("api_token") or request.values.get("api_token") or "").strip()


def _get_first_user_id():
    """返回第一个未禁用用户的 id，用于 API Token 上传时的历史记录。"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE disabled = 0 ORDER BY id LIMIT 1")
        row = c.fetchone()
    return row["id"] if row else None


@app.route("/api/upload-by-token", methods=["POST"])
def api_upload_by_token():
    """
    使用 .env 中的 API_TOKEN 通过 curl 等工具直传升级包。
    认证：Header「Authorization: Bearer <API_TOKEN>」或 表单/查询参数 api_token=xxx。
    表单：file（或 filepond）、config_id（必填，上传配置 ID）。
    """
    if not config.API_TOKEN:
        return jsonify({"success": 0, "msg": "API Token 未配置，该接口已禁用"}), 503
    token = _get_api_token_from_request()
    if token != config.API_TOKEN:
        return jsonify({"success": 0, "msg": "API Token 无效"}), 401
    user_id = _get_first_user_id()
    if user_id is None:
        return jsonify({"success": 0, "msg": "系统中无可用用户，无法记录上传"}), 503
    f = request.files.get("file") or request.files.get("filepond")
    if not f or not f.filename:
        return jsonify({"success": 0, "msg": "未选择文件"}), 400
    raw = request.form.get("config_id") or request.values.get("config_id")
    if not raw:
        return jsonify({"success": 0, "msg": "缺少 config_id（上传配置 ID）"}), 400
    try:
        config_id = int(raw)
    except (TypeError, ValueError):
        return jsonify({"success": 0, "msg": "config_id 必须为整数"}), 400
    result = save_by_config(config_id, f, user_id)
    path, err = result[0], result[1]
    version_seq = result[2] if len(result) > 2 else 0
    version_str = result[3] if len(result) > 3 else None
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    out = {"success": 1, "msg": "上传成功", "data": path}
    if version_seq:
        out["version_seq"] = version_seq
    if version_str:
        out["version"] = version_str
    return jsonify(out)


@app.route("/api/upload-configs", methods=["GET"])
@require_auth
def api_list_upload_configs():
    """上传配置列表（所有登录用户可读，用于上传页选择配置）。"""
    items = list_upload_configs()
    for x in items:
        x["created_at"] = (x.get("created_at") or "").__str__()[:19].replace("T", " ")
    return jsonify({"success": 1, "data": items})


@app.route("/api/upload-configs", methods=["POST"])
@require_auth
@require_admin
def api_create_upload_config():
    """新增上传配置。"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    target_path = (data.get("target_path") or "").strip()
    action = (data.get("action") or "copy").strip().lower()
    description = (data.get("description") or "").strip()
    current_version = (data.get("current_version") or "").strip()
    rid, err = create_upload_config(name, target_path, action, description, current_version)
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    return jsonify({"success": 1, "msg": "添加成功", "id": rid})


@app.route("/api/upload-configs/<int:config_id>", methods=["PUT"])
@require_auth
@require_admin
def api_update_upload_config(config_id):
    """修改上传配置。"""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    target_path = (data.get("target_path") or "").strip()
    action = (data.get("action") or "copy").strip().lower()
    description = (data.get("description") or "").strip()
    current_version = (data.get("current_version") or "").strip()
    err = update_upload_config(config_id, name, target_path, action, description, current_version)
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    return jsonify({"success": 1, "msg": "保存成功"})


@app.route("/api/upload-configs/<int:config_id>", methods=["DELETE"])
@require_auth
@require_admin
def api_delete_upload_config(config_id):
    """删除上传配置。"""
    if not delete_upload_config(config_id):
        return jsonify({"success": 0, "msg": "记录不存在或已删除"}), 404
    return jsonify({"success": 1, "msg": "已删除"})


@app.route("/api/upload/jar", methods=["POST"])
@require_auth
def api_upload_jar():
    f = request.files.get("file")
    path, err = save_jar(f, request.current_user["user_id"])
    if err:
        return jsonify({"success": 0, "msg": err})
    return jsonify({"success": 1, "msg": "上传成功", "data": path})


@app.route("/api/upload/dist_zip", methods=["POST"])
@require_auth
def api_upload_dist_zip():
    f = request.files.get("file")
    path, err = save_dist_zip(f, request.current_user["user_id"])
    if err:
        return jsonify({"success": 0, "msg": err})
    return jsonify({"success": 1, "msg": "上传并解压成功", "data": path})


@app.route("/api/history", methods=["GET"])
@require_auth
def api_history():
    limit = request.args.get("limit", 500, type=int)
    items = list_history(user_id=request.current_user["user_id"], limit=limit)
    for x in items:
        x["created_at"] = x["created_at"] if isinstance(x["created_at"], str) else (x["created_at"] or "").replace("T", " ")[:19]
    return jsonify({"success": 1, "data": items})


@app.route("/api/versions", methods=["GET"])
@require_auth
def api_versions():
    """上传历史列表（保留兼容，版本号优先用 version_str）。"""
    limit = request.args.get("limit", 500, type=int)
    items = list_history(user_id=None, limit=limit)
    out = []
    for x in items:
        ts = x.get("created_at")
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(ts, str) and "T" in ts:
            ts = ts.replace("T", " ")[:19]
        version_display = x.get("version_str") or x.get("version_seq")
        if version_display is None:
            version_display = x.get("file_name", "").replace(".jar", "").replace(".zip", "")
        out.append({
            "id": x["id"],
            "version": version_display,
            "path": x.get("file_path", ""),
            "file_type": x.get("file_type", ""),
            "md5": "-",
            "created_at": ts,
        })
    return jsonify({"success": 1, "data": out})


@app.route("/api/package-versions", methods=["GET"])
@require_auth
def api_package_versions():
    """版本表列表：配置名、包名、版本号、最后更新时间。"""
    items = list_package_versions()
    for x in items:
        ts = x.get("updated_at")
        if hasattr(ts, "strftime"):
            x["updated_at"] = ts.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(ts, str) and ts and "T" in ts:
            x["updated_at"] = ts.replace("T", " ")[:19]
    return jsonify({"success": 1, "data": items})


@app.route("/api/download/<int:hid>", methods=["GET"])
@require_auth
def api_download(hid):
    path, name = get_file_path_for_download(hid, request.current_user["user_id"])
    if path is None:
        return jsonify({"success": 0, "msg": name}), 404
    if not os.path.isfile(path):
        return jsonify({"success": 0, "msg": "文件不存在"}), 404
    return send_file(path, as_attachment=True, download_name=name)


@app.route("/api/config/paths", methods=["GET"])
@require_auth
@require_admin
def api_get_paths():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, path_type, target_path, description FROM upload_paths ORDER BY path_type")
        rows = c.fetchall()
    data = [dict_from_row(r) for r in rows]
    return jsonify({"success": 1, "data": data})


@app.route("/api/config/paths", methods=["POST"])
@require_auth
@require_admin
def api_set_path():
    data = request.get_json(silent=True) or {}
    path_type = (data.get("path_type") or "").strip()
    target_path = (data.get("target_path") or "").strip()
    if path_type not in ("jar", "dist_zip"):
        return jsonify({"success": 0, "msg": "path_type 须为 jar 或 dist_zip"})
    if not target_path:
        return jsonify({"success": 0, "msg": "target_path 不能为空"})
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE upload_paths SET target_path = ?, description = COALESCE(?, description) WHERE path_type = ?",
            (target_path, data.get("description"), path_type)
        )
        if c.rowcount == 0:
            c.execute(
                "INSERT INTO upload_paths (path_type, target_path, description) VALUES (?, ?, ?)",
                (path_type, target_path, data.get("description") or "")
            )
    return jsonify({"success": 1, "msg": "保存成功"})


@app.route("/api/config/cleanup", methods=["GET"])
@require_auth
@require_admin
def api_get_cleanup():
    cfg = get_cleanup_config()
    return jsonify({"success": 1, "data": cfg})


@app.route("/api/config/cleanup", methods=["POST"])
@require_auth
@require_admin
def api_set_cleanup():
    data = request.get_json(silent=True) or {}
    months = data.get("keep_months", config.DEFAULT_CLEANUP_MONTHS)
    try:
        months = int(months)
    except (TypeError, ValueError):
        months = config.DEFAULT_CLEANUP_MONTHS
    if months < 1:
        months = 1
    set_cleanup_config(months)
    return jsonify({"success": 1, "msg": "已设置保留 %d 个月" % months})


@app.route("/api/cleanup/run", methods=["POST"])
@require_auth
@require_admin
def api_run_cleanup():
    deleted, err = run_cleanup()
    if err:
        return jsonify({"success": 0, "msg": err})
    return jsonify({"success": 1, "msg": "已清理 %d 条历史记录" % deleted, "deleted": deleted})


@app.route("/api/version", methods=["POST"])
@require_auth
def api_version():
    """提交版本信息（上传时已记录历史，此接口仅兼容前端）"""
    data = request.get_json(silent=True) or request.form
    if not data:
        return jsonify({"success": 1, "msg": "已记录"})
    return jsonify({"success": 1, "msg": "提交成功"})


@app.route("/api/del_versions", methods=["POST"])
@require_auth
def api_del_version():
    vid = request.args.get("id", type=int)
    if not vid:
        return jsonify({"success": 0, "msg": "缺少 id"})
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM upload_history WHERE id = ?", (vid,))
    return jsonify({"success": 1, "msg": "删除成功"})


# ---------- 用户管理（仅管理员） ----------


@app.route("/api/users", methods=["GET"])
@require_auth
@require_admin
def api_list_users():
    users = list_users()
    for u in users:
        u["created_at"] = (u.get("created_at") or "").__str__()[:19].replace("T", " ")
    return jsonify({"success": 1, "data": users})


@app.route("/api/users", methods=["POST"])
@require_auth
@require_admin
def api_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "user").strip().lower()
    uid, err = create_user(username, password, role)
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    return jsonify({"success": 1, "msg": "添加成功", "id": uid})


@app.route("/api/users/<int:uid>", methods=["PUT"])
@require_auth
@require_admin
def api_update_user(uid):
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    role = (data.get("role") or "user").strip().lower()
    new_password = data.get("new_password") or data.get("password") or ""
    err = update_user(uid, username, role)
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    if new_password and len(new_password) >= 5:
        err = set_user_password(uid, new_password)
        if err:
            return jsonify({"success": 0, "msg": err}), 400
    return jsonify({"success": 1, "msg": "保存成功"})


@app.route("/api/users/<int:uid>", methods=["DELETE"])
@require_auth
@require_admin
def api_delete_user(uid):
    err = delete_user(uid, request.current_user["user_id"])
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    return jsonify({"success": 1, "msg": "已删除"})


@app.route("/api/users/<int:uid>/disabled", methods=["POST"])
@require_auth
@require_admin
def api_set_user_disabled(uid):
    data = request.get_json(silent=True) or {}
    disabled = bool(data.get("disabled"))
    err = set_user_disabled(uid, disabled)
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    return jsonify({"success": 1, "msg": "已禁用" if disabled else "已启用"})


@app.route("/api/users/<int:uid>/password", methods=["POST"])
@require_auth
@require_admin
def api_set_user_password(uid):
    data = request.get_json(silent=True) or {}
    new_password = data.get("new_password") or data.get("password") or ""
    err = set_user_password(uid, new_password)
    if err:
        return jsonify({"success": 0, "msg": err}), 400
    return jsonify({"success": 1, "msg": "密码已修改"})


@app.route("/<path:path>")
def serve_web(path):
    """将非 API 的请求作为静态资源从 web 目录提供（如 login.html、css、js 等）"""
    if path.startswith("api/"):
        abort(404)
    full = os.path.join(app.static_folder, path)
    if os.path.isfile(full):
        return send_file(full)
    if os.path.isdir(full):
        index_html = os.path.join(full, "index.html")
        if os.path.isfile(index_html):
            return send_file(index_html)
    abort(404)


def main():
    os.makedirs(config.UPLOAD_ROOT, exist_ok=True)
    init_db()
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)


if __name__ == "__main__":
    main()
