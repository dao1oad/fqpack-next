#!/usr/bin/env python3
"""
Bootstrap the active TradingAgents-CN config to expose deepseek-reasoner by default.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.core.database import close_db, init_db
from app.services.config_service import ConfigService


async def bootstrap_reasoner_defaults() -> None:
    await init_db()
    try:
        service = ConfigService()
        ok = await service.ensure_deepseek_reasoner_defaults()
        if not ok:
            raise RuntimeError("failed to ensure deepseek-reasoner defaults")
        print("deepseek-reasoner defaults ensured")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(bootstrap_reasoner_defaults())
