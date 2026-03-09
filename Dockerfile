# 应用升级系统 - Docker 镜像
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码与静态资源（.dockerignore 已排除 .env、data、uploads 等）
COPY . .

# 容器内 data、uploads 目录由挂载或运行时创建，确保存在
RUN mkdir -p /app/data /app/uploads

EXPOSE 5000

# 通过环境变量或挂载的 .env 配置；默认 5000 端口
ENV HOST=0.0.0.0
ENV PORT=5000

CMD ["python", "app.py"]
