from app.infrastructure.mcp.base_client import MCPToolClient

class EmailToolClient(MCPToolClient):
    async def send_email(self, to: str, subject: str, body: str) -> dict:
        """发送面试邀请邮件，返回结果含 email_id"""
        return await self.call_tool("send_email", {
            "to": to,
            "subject": subject,
            "body": body
        })