"""应用配置 —— 需求文档 §24（模型 / 密钥一律走环境变量）。

设计要点：
* 单一 `Settings` 源，所有 app（api / worker / mcp-server）共用，避免配置漂移；
* 密钥只允许从环境注入，源码中不得出现任何硬编码凭据；
* 生产环境启动即做 fail-fast 校验，防止带着弱 SECRET_KEY / 开放 CORS 上线。
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_PRODUCTION_SECRET_LENGTH = 32


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """进程配置。字段名即环境变量名（大写），支持 .env 文件。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ------------------------------------------------------------------ 应用
    app_env: Environment = Environment.DEVELOPMENT
    app_debug: bool = False
    app_version: str = "0.1.0"
    service_name: str = "dw-api"
    log_level: str = "INFO"
    log_json: bool = True
    # 逗号分隔字符串而非 list：避免 pydantic-settings 对复杂类型做 JSON 解析导致
    # 形如 `http://a.com,http://b.com` 的配置被误判为非法 JSON。
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # ------------------------------------------------------------------ 安全
    secret_key: str = "local-development-secret-key-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # ------------------------------------------------------------------ Postgres
    postgres_host: str = "localhost"
    # 宿主机映射端口刻意避开 5432：本机常已存在 Windows PostgreSQL 服务占用该端口
    postgres_port: int = 55432
    postgres_user: str = "decoration"
    postgres_password: str = "decoration"
    postgres_db: str = "workbench"
    # 显式 DSN 覆盖；留空则按上面字段拼装
    database_url: str | None = None

    # ------------------------------------------------------------------ Redis
    redis_url: str = "redis://localhost:6379/0"

    # ------------------------------------------------------------------ Kafka
    kafka_bootstrap_servers: str = "localhost:9094"
    kafka_consumer_group: str = "dw-workbench"

    # ------------------------------------------------------------------ RAG（Phase 4）
    # 嵌入器类型：fake（确定性、零外部依赖，供 CI/本地）或 openai（真实语义嵌入）。
    rag_embedder_kind: str = "fake"
    # 向量维度：必须与迁移建表维度一致；切换为 openai 时需同步改成模型维度（如 1536）并重新迁移。
    rag_embedding_dim: int = 256
    rag_openai_api_key: str | None = None
    rag_openai_base_url: str | None = None
    rag_openai_embed_model: str = "text-embedding-3-small"

    # ------------------------------------------------------------------ 探针
    health_probe_timeout_ms: int = 3000

    # ------------------------------------------------------------------ 可观测（Phase 9）
    # 默认关闭：不装配 TracerProvider，全部 span 退化为 no-op，行为与接入前一致。
    otel_enabled: bool = False
    # 同时置 otel_enabled=True 才会真正导出；导出器需装 extras：dw-infrastructure[otel]
    otel_exporter_otlp_endpoint: str | None = None
    # 留空则回落到 service_name
    otel_service_name: str | None = None
    otel_trace_sample_ratio: float = 1.0

    # ------------------------------------------------------------------ 派生属性
    @property
    def async_database_dsn(self) -> str:
        """SQLAlchemy + asyncpg 使用的 DSN。"""
        if self.database_url:
            return self.database_url
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def health_probe_timeout_s(self) -> float:
        return self.health_probe_timeout_ms / 1000

    @model_validator(mode="after")
    def _validate_production_safety(self) -> Settings:
        """生产环境 fail-fast：宁可启动失败，也不带着不安全配置上线。"""
        if self.app_env is not Environment.PRODUCTION:
            return self

        problems: list[str] = []
        if len(self.secret_key) < MIN_PRODUCTION_SECRET_LENGTH:
            problems.append(f"SECRET_KEY 长度必须 >= {MIN_PRODUCTION_SECRET_LENGTH}")
        if self.secret_key.startswith("local-development"):
            problems.append("SECRET_KEY 仍是开发默认值")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS 不得包含 '*'")
        if self.app_debug:
            problems.append("APP_DEBUG 在生产环境必须为 false")

        if problems:
            raise ValueError("生产环境配置不安全: " + "; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内缓存配置。测试需要重载时用 `get_settings.cache_clear()`。"""
    return Settings()
