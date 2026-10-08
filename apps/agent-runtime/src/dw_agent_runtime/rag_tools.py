"""AfterSales 工具（RAG 驱动）—— Phase 4。

三个工具把 RAG 证据底座接到售后诊断技能上：
* `case_search`  混合检索相关售后知识/案例（向量 + BM25 + RRF）；
* `root_cause`   基于 RAG 证据 + 关键词规则，产出根因假设与处置建议；
* `case_match`   用向量相似度匹配最相似的历史案例。

工具只决定「调 RAG 取什么证据」，根因判断由 `skills.run_aftersales_diagnosis` 编排。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from dw_agent_runtime.tools import RiskLevel, ToolContext, ToolDefinition
from dw_infrastructure.config import get_settings
from dw_infrastructure.rag.embeddings import build_embedder
from dw_infrastructure.rag.retrieval import IdentityReranker, retrieve
from dw_infrastructure.rag.store import DocumentStore

# 关键词 → (根因类别, 处置建议)。规则简单、可解释，作为 RAG 证据的补充判断。
_KEYWORD_RULES: list[tuple[tuple[str, ...], str, list[str]]] = [
    (
        ("渗水", "漏水", "水渍", "潮湿", "返潮"),
        "防水/管道渗漏",
        ["排查卫生间与阳台防水层", "检查给排水管接口与穿墙套管", "做 24h 闭水试验确认渗漏点"],
    ),
    (
        ("开裂", "裂缝", "空鼓"),
        "基层/抹灰开裂",
        ["检查墙体基层处理", "复核抹灰层空鼓率", "评估是否为结构性裂缝并请结构确认"],
    ),
    (
        ("返工", "整改", "不合格", "验收不通过"),
        "施工质量不达标",
        ["复核施工与验收记录", "安排第三方复检", "制定限时整改方案并留痕"],
    ),
    (
        ("异味", "发霉", "霉斑"),
        "潮湿霉变",
        ["排查通风与除湿", "检查隐蔽部位渗水", "做防霉处理并更换受损材料"],
    ),
]


def _build_store(ctx: ToolContext) -> DocumentStore:
    settings = get_settings()
    embedder = build_embedder(settings)
    return DocumentStore(ctx.session, embedder, settings.rag_embedding_dim)


def _apply_rules(issue: str) -> tuple[str, list[str]]:
    matched = [rule for rule in _KEYWORD_RULES if any(kw in issue for kw in rule[0])]
    if not matched:
        return (
            "通用售后问题",
            ["现场勘察并拍照留证", "对照合同与质保条款", "派单给对应工种复核"],
        )
    # 取命中关键词最多的规则
    best = max(matched, key=lambda rule: sum(kw in issue for kw in rule[0]))
    return best[1], best[2]


# -----------------------------------------------------------------------------
# case_search
# -----------------------------------------------------------------------------
class CaseSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)


async def _case_search(payload: CaseSearchIn, ctx: ToolContext) -> dict[str, Any]:
    store = _build_store(ctx)
    result = await retrieve(store, payload.query, k=payload.k, reranker=IdentityReranker())
    return {
        "query": result.query,
        "strategy": result.strategy,
        "chunks": [chunk.model_dump(mode="json") for chunk in result.chunks],
    }


# -----------------------------------------------------------------------------
# root_cause
# -----------------------------------------------------------------------------
class RootCauseIn(BaseModel):
    issue: str = Field(min_length=1, max_length=1000)


async def _root_cause(payload: RootCauseIn, ctx: ToolContext) -> dict[str, Any]:
    store = _build_store(ctx)
    result = await retrieve(store, payload.issue, k=5, reranker=IdentityReranker())
    hypothesis, suggestions = _apply_rules(payload.issue)
    return {
        "issue": payload.issue,
        "hypothesis": hypothesis,
        "suggested_actions": suggestions,
        # 证据越充分置信度越高（封顶 0.9），但规则判断本身保持可解释
        "confidence": round(min(0.9, 0.5 + 0.08 * len(result.chunks)), 2),
        "evidence": [chunk.model_dump(mode="json") for chunk in result.chunks],
    }


# -----------------------------------------------------------------------------
# case_match
# -----------------------------------------------------------------------------
class CaseMatchIn(BaseModel):
    issue: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=3, ge=1, le=20)


async def _case_match(payload: CaseMatchIn, ctx: ToolContext) -> dict[str, Any]:
    store = _build_store(ctx)
    hits = await store.similar_cases(payload.issue, k=payload.k)
    return {
        "issue": payload.issue,
        "cases": [
            {
                "chunk_id": str(hit.id),
                "source": hit.source,
                "similarity": round(hit.score, 6),
                "summary": hit.content,
                "metadata": hit.metadata,
            }
            for hit in hits
        ],
    }


AFTERSALES_TOOLS: dict[str, ToolDefinition[Any]] = {
    "case_search": ToolDefinition(
        tool_id="case_search",
        description="混合检索相关售后知识/案例（向量 + BM25 + RRF 融合）",
        required_scopes=("project:read",),
        risk_level=RiskLevel.L0,
        input_model=CaseSearchIn,
        handler=_case_search,
    ),
    "root_cause": ToolDefinition(
        tool_id="root_cause",
        description="基于 RAG 证据与关键词规则，产出根因假设与处置建议",
        required_scopes=("project:read",),
        risk_level=RiskLevel.L0,
        input_model=RootCauseIn,
        handler=_root_cause,
    ),
    "case_match": ToolDefinition(
        tool_id="case_match",
        description="用向量相似度匹配最相似的历史售后案例",
        required_scopes=("project:read",),
        risk_level=RiskLevel.L0,
        input_model=CaseMatchIn,
        handler=_case_match,
    ),
}

