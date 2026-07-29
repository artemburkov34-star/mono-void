"""Mono Core 4.0 — FastAPI entry point (UI / PWA / Electron)."""
from __future__ import annotations

import uvicorn

from api.server import app
from core.config import config
from core.logger import audit


def main() -> None:
    audit.info(
        f"api boot env={config.ENVIRONMENT} on {config.API_HOST}:{config.API_PORT}",
        extra={"actor": "system", "action": "api.boot"},
    )
    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
