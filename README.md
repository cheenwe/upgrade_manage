# 应用升级系统

[![GitHub](https://img.shields.io/badge/GitHub-cheenwe%2Fupgrade__manage-blue?logo=github)](https://github.com/cheenwe/upgrade_manage) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python + Flask + SQLite 实现的应用升级管理：多上传配置（复制 / unzip / tar）、版本表、上传历史与下载、JWT 登录与管理员/普通用户角色，支持 API Token 通过 curl 或 CI 上传。

**仓库地址**：<https://github.com/cheenwe/upgrade_manage>

---

## 功能

- **Python + SQLite** 后端，数据存于 `data/upgrade.db`，配置通过 `.env` 管理
- **多上传配置**：系统设置中维护多条配置（目标路径、操作：仅复制 / unzip / tar），上传时选择配置，版本号按配置与包名自动递增
- **版本管理**：按「配置 + 包名」展示版本表，支持复制 curl 上传命令
- **上传历史**：记录每次上传（用户、文件名、路径、时间），支持下载
- **账号与权限**：JWT 登录；管理员可进入系统设置、用户管理，普通用户仅升级相关功能
- **API Token 上传**：`.env` 配置 `API_TOKEN` 后，可通过 `POST /api/upload-by-token` 使用 curl 或 CI 上传，无需登录
- **自动清理**：可配置保留最近 N 个月的历史，支持立即执行清理
- **前端**：`web/` 静态页（Tabler 风格），响应式布局

## 快速开始

### 克隆与安装

```bash
git clone https://github.com/cheenwe/upgrade_manage.git
cd upgrade_manage
pip install -r requirements.txt
```

### 配置（可选）

```bash
cp .env.example .env
# 编辑 .env：端口、SECRET_KEY、API_TOKEN、默认管理员等，详见 .env.example
```

### 运行

```bash
python app.py
```

浏览器访问：<http://127.0.0.1:5000/>（默认端口 5000，可在 `.env` 中修改为如 8080）。  
首次运行会自动创建数据库与默认管理员（见 `.env` 中 `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD`）。

- **登录**：<http://127.0.0.1:5000/login.html>
- **上传新版本**：选择上传配置后上传 .jar / .zip / .tar 等
- **版本管理**：查看版本表、复制 curl 上传命令
- **升级历史**：查看与下载历史记录
- **系统设置 / 用户管理**：仅管理员可见

### Docker 运行

需先有 `.env`（可 `cp .env.example .env` 后修改）。

```bash
# 构建并启动（挂载主机 /opt、本地 data 与 uploads）
docker compose up -d --build
```

默认映射端口 5000；若 `.env` 中设置了 `PORT=8080`，则主机 8080 → 容器 5000。  
**卷挂载**：

- `./data` → 容器内数据库目录（持久化）
- `./uploads` → 容器内上传缓存目录（持久化）
- `/opt` → 主机 `/opt` 挂载到容器内 `/opt`，上传配置中的目标路径若为 `/opt/xxx` 会写入主机对应目录

仅使用镜像、不 compose 时示例：

```bash
docker build -t upgrade_manage .
docker run -d -p 5000:5000 -v $(pwd)/data:/app/data -v $(pwd)/uploads:/app/uploads -v /opt:/opt --env-file .env upgrade_manage
```

## 环境变量（.env）

| 变量 | 说明 |
|------|------|
| `HOST` | 监听地址，默认 `0.0.0.0` |
| `PORT` | 端口，默认 `5000` |
| `DEBUG` | 是否调试，默认 `true` |
| `DATABASE` | SQLite 路径，空则 `data/upgrade.db` |
| `UPLOAD_ROOT` | 上传根目录，空则 `uploads/` |
| `SECRET_KEY` | JWT/加密密钥，**生产务必修改** |
| `JWT_EXPIRE_DAYS` | 登录 Token 有效天数 |
| `API_TOKEN` | 留空则禁用 `/api/upload-by-token`；设置后可用 curl/CI 上传 |
| `DEFAULT_ADMIN_*` | 仅首次无用户时创建默认管理员 |

更多见 `.env.example`。

## curl 上传示例

配置 `API_TOKEN` 后：

```bash
curl -X POST -H "Authorization: Bearer YOUR_API_TOKEN" \
  -F "file=@./your-package.zip" -F "config_id=1" \
  "https://your-server/api/upload-by-token"
```

版本管理页每个版本提供「复制上传命令」按钮，可复制带对应 `config_id` 的完整命令。

## 目录结构

| 路径 | 说明 |
|------|------|
| `app.py` | Flask 入口与 API 路由 |
| `config.py` | 配置（读取 .env） |
| `db.py` | SQLite 初始化与表结构 |
| `auth.py` | 登录与 JWT、角色校验 |
| `upload_handler.py` | 按配置上传、版本表、历史 |
| `cleanup.py` | 清理配置与执行 |
| `web/` | 静态站点（首页、登录、上传、版本、历史、设置、文档等） |
| `data/` | 数据库文件（自动创建） |
| `uploads/` | 默认上传根目录（可配置） |

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/login` | 登录，返回 token |
| GET | `/api/me` | 当前用户信息（用户名、是否管理员） |
| POST | `/api/uploads` | 统一上传（需登录），表单：`file`、`config_id` |
| POST | `/api/upload-by-token` | 使用 API_TOKEN 上传（表单：`file`、`config_id`） |
| GET | `/api/upload-configs` | 上传配置列表（登录可读） |
| GET | `/api/package-versions` | 版本表列表 |
| GET | `/api/history` | 当前用户上传历史 |
| GET | `/api/download/<id>` | 下载历史文件 |
| GET/POST | `/api/config/cleanup` | 清理配置（保留月数） |
| POST | `/api/cleanup/run` | 执行清理（管理员） |
| GET/POST/PUT/DELETE | `/api/users` 等 | 用户管理（管理员） |

## 文档

部署与配置说明见站点内「文档」→ [安装与部署](web/doc_install.html)。

## License

本项目采用 [MIT License](LICENSE)。可自由使用、修改与再分发，请保留版权与许可声明。
