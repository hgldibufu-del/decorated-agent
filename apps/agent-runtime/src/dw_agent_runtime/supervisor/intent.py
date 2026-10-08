"""Intent Router —— 需求文档 §4。

为什么是**规则**而不是 LLM：
* Phase 3 的目标是先把编排骨架钉死，意图识别的准确性可以在 Phase 4 之后
  换成模型（把 `route()` 替换成模型调用即可，签名不变）；
* 规则路由可单测、零成本、结果可解释（返回命中的关键词），
  这对「用户问为什么派了这个 Agent」的追问很关键。
"""

from __future__ import annotations

import re

from dw_schemas.supervisor import IntentResult, IntentType

PROJECT_CODE_PATTERN = re.compile(r"\b(GC-\d{4}-\d{3})\b", re.IGNORECASE)

# 关键词 → 意图。顺序即优先级：更具体的意图排在前面。
INTENT_KEYWORDS: list[tuple[IntentType, tuple[str, ...]]] = [
    (
        IntentType.AFTERSALES_DIAGNOSIS,
        ("渗水", "漏水", "维修", "售后", "工单", "整改", "开裂", "返工"),
    ),
    (
        IntentType.QUOTE_ESTIMATE,
        ("报价", "预算", "造价", "多少钱", "套餐", "材料价格", "涨价"),
    ),
    (
        IntentType.DESIGN_PROPOSAL,
        ("设计", "风格", "户型", "布局", "方案", "效果图"),
    ),
    (
        IntentType.CONSTRUCTION_REVIEW,
        ("施工", "进度", "工期", "验收", "延期", "工地"),
    ),
    (
        IntentType.PROJECT_COMPARE,
        ("对比", "比较", "两个项目", "差异"),
    ),
    (
        IntentType.PROJECT_OVERVIEW,
        ("概览", "概况", "看一下", "了解", "项目情况", "进展如何"),
    ),
]

# 意图优先级：**具体意图优先于兜底意图**。
# 只用「命中词数量」会让「卫生间渗水，看一下项目概况」被判成概览 ——
# 因为泛化措辞往往更长。先比优先级，再比命中数。
INTENT_PRIORITY: dict[IntentType, int] = {
    IntentType.DIRECT_REQUEST: 0,  # 不参与路由，仅用于落库的直接请求计划
    IntentType.AFTERSALES_DIAGNOSIS: 3,
    IntentType.QUOTE_ESTIMATE: 3,
    IntentType.DESIGN_PROPOSAL: 3,
    IntentType.CONSTRUCTION_REVIEW: 3,
    IntentType.PROJECT_COMPARE: 2,
    IntentType.PROJECT_OVERVIEW: 1,
}

# 每个意图的基础置信度：命中词越多置信度越高，但上限 0.95
BASE_CONFIDENCE: dict[IntentType, float] = {
    IntentType.DIRECT_REQUEST: 0.0,
    IntentType.AFTERSALES_DIAGNOSIS: 0.7,
    IntentType.QUOTE_ESTIMATE: 0.7,
    IntentType.DESIGN_PROPOSAL: 0.7,
    IntentType.CONSTRUCTION_REVIEW: 0.7,
    IntentType.PROJECT_COMPARE: 0.6,
    IntentType.PROJECT_OVERVIEW: 0.6,
}


def route(message: str) -> IntentResult:
    """把一句自然语言映射为意图。

    规则：取命中关键词最多的意图；无命中时返回 `unknown`（置信度 0），
    由上层决定是追问还是回退到默认概览 —— 绝不强行猜测。
    """
    mentioned_code = extract_project_code(message)

    best_intent = IntentType.UNKNOWN
    best_keywords: list[str] = []
    best_rank = (-1, -1)

    for intent, keywords in INTENT_KEYWORDS:
        matched = [keyword for keyword in keywords if keyword in message]
        if not matched:
            continue
        rank = (INTENT_PRIORITY[intent], len(matched))
        if rank > best_rank:
            best_intent = intent
            best_keywords = matched
            best_rank = rank

    if best_intent is IntentType.UNKNOWN or not best_keywords:
        return IntentResult(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            matched_keywords=[],
            mentioned_project_code=mentioned_code,
        )

    confidence = min(0.95, BASE_CONFIDENCE[best_intent] + 0.1 * (len(best_keywords) - 1))
    return IntentResult(
        intent=best_intent,
        confidence=round(confidence, 2),
        matched_keywords=best_keywords,
        mentioned_project_code=mentioned_code,
    )


def extract_project_code(message: str) -> str | None:
    match = PROJECT_CODE_PATTERN.search(message)
    return match.group(1).upper() if match else None
