"""配置校验单测 —— 需求文档 §13 / §24。"""

from __future__ import annotations

import pytest
from dw_infrastructure.config import Environment, Settings, get_settings
from pydantic import ValidationError


def test_defaults_are_development_friendly():
    settings = Settings()
    assert settings.app_env is Environment.DEVELOPMENT
    assert settings.service_name == "dw-api"
    assert settings.health_probe_timeout_s == pytest.approx(3.0)


def test_async_dsn_is_assembled_from_parts():
    settings = Settings(
        postgres_user="decoration",
        postgres_password="decoration",
        postgres_host="localhost",
        postgres_port=5432,
        postgres_db="workbench",
        database_url=None,
    )
    assert (
        settings.async_database_dsn
        == "postgresql+asyncpg://decoration:decoration@localhost:5432/workbench"
    )


def test_dsn_password_is_url_encoded():
    settings = Settings(postgres_password="p@ss/w:rd", database_url=None)
    assert "p%40ss%2Fw%3Ard" in settings.async_database_dsn


def test_explicit_database_url_wins():
    override = "postgresql+asyncpg://u:p@db.internal:5432/other"
    assert Settings(database_url=override).async_database_dsn == override


def test_cors_origins_are_split_and_trimmed():
    settings = Settings(cors_origins="http://a.com, http://b.com,,")
    assert settings.cors_origin_list == ["http://a.com", "http://b.com"]


def test_production_rejects_weak_secret():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(
            app_env=Environment.PRODUCTION,
            secret_key="short",
            cors_origins="https://app.example.com",
            app_debug=False,
        )


def test_production_rejects_development_secret():
    long_dev_secret = "local-development-secret-key-change-me-000000000000"
    with pytest.raises(ValidationError, match="开发默认值"):
        Settings(
            app_env=Environment.PRODUCTION,
            secret_key=long_dev_secret,
            cors_origins="https://app.example.com",
            app_debug=False,
        )


def test_production_rejects_wildcard_cors_and_debug():
    strong_secret = "0" * 40
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            app_env=Environment.PRODUCTION,
            secret_key=strong_secret,
            cors_origins="*",
            app_debug=True,
        )
    message = str(excinfo.value)
    assert "CORS_ORIGINS" in message
    assert "APP_DEBUG" in message


def test_production_accepts_hardened_config():
    settings = Settings(
        app_env=Environment.PRODUCTION,
        secret_key="0" * 40,
        cors_origins="https://app.example.com",
        app_debug=False,
    )
    assert settings.app_env is Environment.PRODUCTION


def test_get_settings_is_cached():
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second
    get_settings.cache_clear()
    assert get_settings() is not first
