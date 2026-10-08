"""AfterSales 端到端集成测试 —— Phase 4（需要真实 PostgreSQL + 已迁移/已 seed）。

验证：提交售后诊断意图 → Supervisor 路由到 aftersales_agent → 计划 → 技能执行体
通过三个 RAG 工具检索证据 → 任务 succeeded 并产出带引用的 aftersales_diagnosis Artifact。
"""

from __future__ import annotations

from dw_domain.repositories.agent_runtime import RegistryRepository
from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_infrastructure.rag.embeddings import FakeEmbedder
from dw_infrastructure.rag.store import DocumentStore
from dw_schemas.agent import AgentType, RiskLevel
from dw_schemas.iam import RoleName


async def _ensure_aftersales(session) -> None:
    """确保 AfterSales 的 Agent / Skill / Tools 已注册（镜像 scripts/seed.py）。"""
    reg = RegistryRepository(session)
    for tool_id, desc in (
        ("case_search", "混合检索相关售后知识/案例"),
        ("root_cause", "基于 RAG 证据与规则产出根因假设"),
        ("case_match", "向量匹配相似历史售后案例"),
    ):
        await reg.ensure_tool(
            tool_id=tool_id,
            description=desc,
            required_scopes=["project:read"],
            risk_level=RiskLevel.L0,
            timeout_ms=5000,
            retry_max_attempts=2,
            fallback_tool_id=None,
        )
    await reg.ensure_skill(
        skill_id="aftersales_diagnosis",
        agent_type=AgentType.AFTERSALES.value,
        version="0.1.0",
        required_scopes=["project:read"],
        risk_level=RiskLevel.L1,
        allowed_tools=["case_search", "root_cause", "case_match"],
    )
    await reg.ensure_agent(
        agent_id="aftersales_agent",
        agent_type=AgentType.AFTERSALES.value,
        description="售后 Agent：根因分析、案例匹配、处置建议",
        version="0.1.0",
        supported_skills=["aftersales_diagnosis"],
        required_scopes=["project:read"],
    )


async def _seed_knowledge(session) -> None:
    settings = get_settings()
    store = DocumentStore(session, FakeEmbedder(settings.rag_embedding_dim), settings.rag_embedding_dim)
    await store.upsert_document(
        title="防水施工规范",
        content="卫生间渗水漏水应做闭水试验，排查防水层与给排水管接口渗漏。",
        source="aftersales-kb",
    )
    await store.upsert_document(
        title="历史案例",
        content="历史案例：某项目卫生间渗水，重做防水层后解决。",
        source="aftersales-case",
        metadata={"kind": "case", "case_id": "C1"},
    )


async def test_aftersales_diagnosis_end_to_end(client, auth_headers, cleaner) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.ADMIN)  # admin 豁免 scope，聚焦诊断链路

    # 注入 RAG 知识库 + 注册 AfterSales 能力
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _seed_knowledge(session)
        await _ensure_aftersales(session)
    await database.dispose()

    created = client.post(
        "/api/v1/runs",
        headers=headers,
        json={"intent": "aftersales_diagnosis", "objective": "卫生间渗水，墙面发霉"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cleaner("agent_runs", "id", body["id"])

    assert body["status"] == "completed"
    assert body["tasks"][0]["skill_id"] == "aftersales_diagnosis"
    assert body["artifact_ids"], "应产出 aftersales_diagnosis Artifact"

    artifact = client.get(
        f"/api/v1/artifacts/{body['artifact_ids'][0]}", headers=headers
    ).json()
    payload = artifact["payload"]

    # 根因来自 RAG 证据 + 规则（渗水 → 防水/管道渗漏）
    assert payload["hypothesis"] == "防水/管道渗漏"
    assert payload["evidence"], "应带 RAG 检索证据"
    assert payload["similar_cases"], "应匹配到相似历史案例"

    # 清理 RAG 数据，避免污染其它用例
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        s2 = DocumentStore(
            session, FakeEmbedder(get_settings().rag_embedding_dim), get_settings().rag_embedding_dim
        )
        await s2.clear()
    await database.dispose()


async def test_skills_lists_aftersales_as_implemented(client, auth_headers) -> None:  # noqa: ANN001
    headers = await auth_headers(role=RoleName.ADMIN)
    # 先确保注册（端到端测试若先跑已注册；这里幂等 ensure）
    database = Database.from_settings(get_settings())
    async with database.session() as session:
        await _ensure_aftersales(session)
    await database.dispose()

    resp = client.get("/api/v1/skills", headers=headers)
    assert resp.status_code == 200, resp.text
    skills = {s["skill_id"]: s for s in resp.json()}
    assert "aftersales_diagnosis" in skills
    assert skills["aftersales_diagnosis"]["agent_type"] == AgentType.AFTERSALES.value
