"""Quote 工具纯逻辑单测（不依赖 DB）：金额计算 / 套餐排序 / 材料检索。"""

from __future__ import annotations

from decimal import Decimal

from dw_agent_runtime.quote_tools import _compute_estimate, _match_items, _rank_packages


def test_compute_estimate_basic():
    line_items, total = _compute_estimate(Decimal("100"), Decimal("28000"), Decimal("1280"))
    assert total == Decimal("156000.00")
    assert line_items[0]["amount"] == "28000.00"
    assert line_items[1]["amount"] == "128000.00"


def test_compute_estimate_rounds_to_cent():
    _, total = _compute_estimate(Decimal("10.5"), Decimal("0"), Decimal("9.99"))
    assert total == Decimal("104.90")


def test_compute_estimate_preserves_precision():
    # 浮点会出错的小数，Decimal 必须精确
    _, total = _compute_estimate(Decimal("33.33"), Decimal("0"), Decimal("0.1"))
    assert str(total) == "3.33"


def test_rank_packages_sorts_ascending_and_computes_total():
    packages = [
        {"id": "1", "name": "高端", "base_price": "48000.00", "price_per_sqm": "1880.00"},
        {"id": "2", "name": "标准", "base_price": "28000.00", "price_per_sqm": "1280.00"},
        {"id": "3", "name": "经济", "base_price": "18000.00", "price_per_sqm": "880.00"},
    ]
    ranked = _rank_packages(Decimal("100"), packages)
    assert [p["name"] for p in ranked] == ["经济", "标准", "高端"]
    assert ranked[0]["total"] == "106000.00"  # 18000 + 88000
    assert ranked[1]["total"] == "156000.00"
    assert ranked[2]["total"] == "236000.00"
    assert ranked[0]["per_sqm_effective"] == "1060.00"


def test_match_items_filters_by_category_and_keyword():
    items = [
        {"category": "硬装", "name": "水电隐蔽工程", "metadata_json": {"keywords": ["水电", "防水"]}},
        {"category": "主材", "name": "实木地板", "metadata_json": {"keywords": ["地板"]}},
        {"category": "软装", "name": "窗帘", "metadata_json": {"keywords": ["软装"]}},
    ]
    hard = _match_items(items, category="硬装")
    assert len(hard) == 1 and hard[0]["name"] == "水电隐蔽工程"

    by_keyword = _match_items(items, keyword="地板")
    assert len(by_keyword) == 1 and by_keyword[0]["name"] == "实木地板"

    no_filter = _match_items(items)
    assert len(no_filter) == 3


def test_match_items_keyword_uses_metadata_keywords():
    items = [
        {"category": "硬装", "name": "墙面基层", "metadata_json": {"keywords": ["乳胶漆"]}},
    ]
    assert _match_items(items, keyword="乳胶漆")
    assert not _match_items(items, keyword="地板")
