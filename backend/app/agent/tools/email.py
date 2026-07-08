"""邮件通知工具。"""
from app.agent.tools.base_tool import BaseTool, ToolContext, ToolInput, ToolResult


class EmailTool(BaseTool):
    name = "email"
    description = "将生成的报告或预警结论发送到指定邮箱。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        # TODO: 接入 SMTP 并校验收件人、主题、附件路径
        return ToolResult(
            summary="【邮件通知（占位）】邮件发送请求已创建，等待 SMTP 配置后执行。",
            data={"email_status": "pending_smtp_config"},
        )
