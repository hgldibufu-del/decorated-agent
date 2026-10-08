-- =============================================================================
-- PostgreSQL 初始化脚本（docker-entrypoint-initdb.d）
-- 仅在首次创建 volume 时执行，之后不会重复执行。
-- =============================================================================

-- pgvector：RAG 向量检索引擎（需求文档 §16）
CREATE EXTENSION IF NOT EXISTS vector;

-- pgcrypto：全局 UUID 主键生成
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- pg_trgm + zhparser 预备：BM25 / 中文全文检索（需求文档 §16）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 业务事实全部落在独立 schema 下，避免与扩展所属 schema 混淆
CREATE SCHEMA IF NOT EXISTS workbench;

-- 让本库的默认 search_path 指向 workbench：
-- 这样 Alembic 与业务表无需在每个模型上写 schema=，也不会误落到 public。
-- 超级用户连接需要显式 `SET search_path` 才能看到这些表。
ALTER DATABASE workbench SET search_path TO workbench, public;

-- 兜底校验：确认 pgvector 可用，缺失时启动即失败，避免运行时才发现
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension is required but not available';
    END IF;
END
$$;
