"""Golden set（检索标准答案）—— Phase 9。

用 **JSON** 而不是 YAML：本项目对依赖极克制，不为此引入 PyYAML；
golden set 只需表达「语料 + 查询 → 相关文档」这一层结构，JSON 足够。

形状：

```json
{
  "name": "aftersales-golden-v1",
  "k": 3,
  "documents": [{"key": "...", "title": "...", "content": "...", "source": "...", "metadata": {}}],
  "cases": [{"query": "...", "relevant": ["<document key>"]}]
}
```

`relevant` 引用的是 **document key**（而非数据库 id），这样语料可以在任意环境
重新摄入而指标不变 —— 评估可复现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_DATASET_NAME = "aftersales_golden.json"


@dataclass(frozen=True, slots=True)
class GoldenDocument:
    key: str
    title: str
    content: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GoldenCase:
    query: str
    relevant: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldenSet:
    name: str
    k: int
    documents: tuple[GoldenDocument, ...]
    cases: tuple[GoldenCase, ...]


def datasets_dir() -> Path:
    return Path(__file__).resolve().parent / "datasets"


def default_dataset_path() -> Path:
    return datasets_dir() / DEFAULT_DATASET_NAME


def load_golden(path: Path | str | None = None) -> GoldenSet:
    """加载并**校验** golden set：引用不存在的文档会直接报错，而不是静默算错。"""
    target = Path(path) if path is not None else default_dataset_path()
    raw = json.loads(target.read_text(encoding="utf-8"))

    documents = tuple(
        GoldenDocument(
            key=item["key"],
            title=item.get("title", item["key"]),
            content=item["content"],
            source=item.get("source", item["key"]),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in raw.get("documents") or []
    )
    cases = tuple(
        GoldenCase(query=item["query"], relevant=tuple(item.get("relevant") or []))
        for item in raw.get("cases") or []
    )
    if not documents or not cases:
        raise ValueError(f"golden set 不完整（documents / cases 不可为空）: {target}")

    known = {document.key for document in documents}
    for case in cases:
        unknown = set(case.relevant) - known
        if unknown:
            raise ValueError(
                f"用例 {case.query!r} 引用了不存在的文档 key: {sorted(unknown)}"
            )

    k = int(raw.get("k", 3))
    if k <= 0:
        raise ValueError(f"k 必须为正整数: {k}")
    return GoldenSet(name=raw.get("name", target.stem), k=k, documents=documents, cases=cases)
