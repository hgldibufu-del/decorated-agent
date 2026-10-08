"""命令行入口：`python -m dw_api`（等价于 uvicorn 以 factory 模式启动）。"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "dw_api.app:create_app",
        factory=True,
        host=os.getenv("UVICORN_HOST", "127.0.0.1"),
        port=int(os.getenv("UVICORN_PORT", "8000")),
        reload=os.getenv("UVICORN_RELOAD", "false").lower() == "true",
    )


if __name__ == "__main__":
    main()
