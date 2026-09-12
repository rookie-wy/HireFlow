"""MCP 工具客户端（email / calendar / 视觉检索），失败不中断主流程。"""
from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp

from app.core.errors import get_logger

log = get_logger(__name__)


class MCPToolClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.base_url}/tools/{tool_name}", json=arguments
                ) as resp:
                    if resp.status >= 400:
                        return {"error": f"mcp status {resp.status}", "result": None}
                    return await resp.json()
        except Exception as exc:  # noqa: BLE001 工具失败降级
            log.warning("MCP tool %s at %s failed: %s", tool_name, self.base_url, exc)
            return {"error": str(exc), "result": None}


def email_client(base_url_override: Optional[str] = None) -> MCPToolClient:
    from app.core.config import get_settings

    return MCPToolClient(base_url_override or get_settings().mcp_email_url)


def calendar_client(base_url_override: Optional[str] = None) -> MCPToolClient:
    from app.core.config import get_settings

    return MCPToolClient(base_url_override or get_settings().mcp_calendar_url)


def visual_client() -> MCPToolClient:
    from app.core.config import get_settings

    return MCPToolClient(get_settings().mcp_visual_url)
