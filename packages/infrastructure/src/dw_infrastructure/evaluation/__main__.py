"""评估 CLI —— Phase 9。

用法：
    py -3 -m dw_infrastructure.evaluation              # 跑内置 golden set
    py -3 -m dw_infrastructure.evaluation <path.json>  # 跑指定 golden set

需要可用的 PostgreSQL + pgvector（与 API 共用同一份 Settings）。
输出为 JSON（含汇总指标与逐案明细），便于接入 CI 或人工比对。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database
from dw_infrastructure.evaluation.runner import evaluate_default
from dw_infrastructure.rag.embeddings import build_embedder
from dw_infrastructure.rag.store import DocumentStore


async def _run(path: Path | None) -> int:
    settings = get_settings()
    database = Database.from_settings(settings)
    try:
        async with database.session() as session:
            store = DocumentStore(
                session, build_embedder(settings), settings.rag_embedding_dim
            )
            report = await evaluate_default(store, path)
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    finally:
        await database.dispose()
    return 0


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    return asyncio.run(_run(path))


if __name__ == "__main__":
    raise SystemExit(main())
