import aiohttp
import asyncio

class MCPToolClient:
    def __init__(self, base_url: str, timeout: int = 5):
        self.base_url = base_url
        self.timeout = timeout

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.base_url}/tools/{tool_name}",
                    json=arguments,
                    timeout=self.timeout
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except asyncio.TimeoutError:
                # 超时返回空，不中断主流程（文档规定）
                return {"error": "timeout", "result": None}
            except Exception as e:
                return {"error": str(e), "result": None}