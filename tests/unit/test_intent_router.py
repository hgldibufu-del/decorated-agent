"""Intent Router 单测（纯函数）。"""

from __future__ import annotations

import pytest
from dw_agent_runtime.supervisor.intent import extract_project_code, route
from dw_schemas.supervisor import IntentType


@pytest.mark.parametrize(
    "message,intent",
    [
        ("卫生间最近渗水，帮我分析原因", IntentType.AFTERSALES_DIAGNOSIS),
        ("这个套餐报价多少钱", IntentType.QUOTE_ESTIMATE),
        ("想要现代简约的设计方案", IntentType.DESIGN_PROPOSAL),
        ("工地施工进度怎么样了", IntentType.CONSTRUCTION_REVIEW),
        ("对比一下这两个项目", IntentType.PROJECT_COMPARE),
        ("看一下项目概况", IntentType.PROJECT_OVERVIEW),
    ],
)
def test_messages_route_to_expected_intent(message: str, intent: IntentType):
    result = route(message)
    assert result.intent is intent
    assert result.confidence > 0
    assert result.matched_keywords


def test_unrecognised_message_is_unknown_not_a_guess():
    result = route("今天天气不错")
    assert result.intent is IntentType.UNKNOWN
    assert result.confidence == 0.0
    assert result.matched_keywords == []


def test_project_code_is_extracted_from_message():
    result = route("看看 GC-2026-003 的情况")
    assert extract_project_code("GC-2026-003 的情况") == "GC-2026-003"
    assert result.mentioned_project_code == "GC-2026-003"


def test_more_keywords_raises_confidence():
    single = route("渗水")
    multiple = route("渗水 漏水 维修")
    assert multiple.confidence > single.confidence


def test_confidence_is_capped():
    assert route("渗水 漏水 维修 整改 开裂 返工 售后 工单").confidence <= 0.95


def test_specific_intent_wins_over_generic():
    """「渗水」同时命中售后与概览关键词时，更具体的售后意图应胜出。"""
    result = route("卫生间渗水，看一下项目概况")
    assert result.intent is IntentType.AFTERSALES_DIAGNOSIS
