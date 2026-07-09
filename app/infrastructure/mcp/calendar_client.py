from app.infrastructure.mcp.base_client import MCPToolClient

class CalendarToolClient(MCPToolClient):
    async def create_event(self, title: str, attendees: list, start_time: str, end_time: str, description: str = "") -> dict:
        return await self.call_tool("calendar_api", {
            "action": "create_event",
            "title": title,
            "attendees": attendees,
            "start_time": start_time,
            "end_time": end_time,
            "description": description
        })

    async def check_availability(self, attendees: list, start_time: str, end_time: str) -> dict:
        return await self.call_tool("calendar_api", {
            "action": "check_availability",
            "attendees": attendees,
            "start": start_time,
            "end": end_time
        })