"""Local dev launcher for the worker on Windows.

`uvicorn app.main:app` fails here before serving a single request: psycopg's
async pool cannot run on the ProactorEventLoop, which is Python's default on
Windows, and the pool times out during lifespan startup with

    Psycopg cannot use the 'ProactorEventLoop' to run in async mode

Setting an event loop *policy* does not fix it. Since 0.36 uvicorn passes an
explicit `loop_factory` to `asyncio.run()`, and an explicit factory overrides
the policy — so the only thing that works is handing uvicorn's server coroutine
to `asyncio.run()` ourselves with a selector loop. `loop="none"` stops uvicorn
supplying a factory of its own.

`tests/conftest.py` solves the same problem the older way, which is why the
suite passes on a machine where the server would not boot.

    ..\\.venv\\Scripts\\python.exe run_worker.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config(
        "app.main:app",
        host=os.environ.get("WORKER_HOST", "127.0.0.1"),
        port=int(os.environ.get("WORKER_PORT", "8000")),
        log_level="info",
        # Do not let uvicorn choose; we pass our own factory below.
        loop="none",
    )
    server = uvicorn.Server(config)

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(server.serve(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
