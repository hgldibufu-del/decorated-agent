"""`dw-mcp-server` 入口：起一个 stdio MCP 服务。

刻意**不**调用 `configure_logging`（它写 stdout），否则会污染协议流；
默认 logging 走 stderr，符合 MCP stdio 约定。
"""

from __future__ import annotations

import asyncio
import os
import sys

from dw_infrastructure.config import get_settings
from dw_infrastructure.db import Database

from dw_mcp_server.bridge import McpBridge
from dw_mcp_server.server import serve


async def _run() -> None:
    settings = get_settings()
    database = Database.from_settings(settings)
    bridge = McpBridge(
        database,
        secret_key=settings.secret_key,
        service_token=os.getenv("DW_MCP_TOKEN"),
    )
    try:
        await serve(sys.stdin, sys.stdout, bridge)
    finally:
        await database.dispose()


def main() -> int:
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
