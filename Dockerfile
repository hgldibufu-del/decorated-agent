# syntax=docker/dockerfile:1
# =============================================================================
# 装修企业 AI Agent Workbench —— API 镜像（构建上下文必须是仓库根目录）
# 多阶段构建：builder 安装依赖，runtime 仅保留运行时 + 非 root 用户
# =============================================================================
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# monorepo 本地包以路径依赖方式安装，需拷贝完整源码树
COPY requirements.txt ./
COPY packages ./packages
COPY apps ./apps
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# =============================================================================
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    # 容器内必须监听 0.0.0.0；默认值保留在宿主机（127.0.0.1）以收敛暴露面
    UVICORN_HOST=0.0.0.0

WORKDIR /app

# 非 root 运行
RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=builder /opt/venv /opt/venv

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/live', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "dw_api"]
