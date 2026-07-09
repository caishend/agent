"""Email notification tool."""
from __future__ import annotations

import mimetypes
import re
import smtplib
from collections.abc import Callable, Iterable
from email.message import EmailMessage
from email.utils import formataddr, getaddresses
from pathlib import Path
from typing import Any

from app.agent.tools.base_tool import ArtifactItem, BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult
from app.config import settings


EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?![\w.+-])",
    re.ASCII,
)


class EmailTool(BaseTool):
    name = "email"
    description = "通过 SMTP 将报告、预警结论或通知发送到指定邮箱。"

    def __init__(
        self,
        smtp_factory: Callable[..., Any] | None = None,
        smtp_ssl_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._smtp_factory = smtp_factory or smtplib.SMTP
        self._smtp_ssl_factory = smtp_ssl_factory or smtplib.SMTP_SSL

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        params = tool_input.params or {}

        recipients, invalid_recipients = self._collect_recipients(params, tool_input.query, "recipients", "to")
        cc, invalid_cc = self._collect_recipients(params, "", "cc")
        bcc, invalid_bcc = self._collect_recipients(params, "", "bcc")
        invalid_all = invalid_recipients + invalid_cc + invalid_bcc

        if invalid_all:
            return self._needs_user_input(
                "邮件发送失败：存在格式不合法的邮箱地址，请重新提供有效收件人邮箱。",
                "invalid_recipients",
                invalid_recipients=invalid_all,
            )
        if not recipients:
            return self._needs_user_input(
                "发送邮件需要收件人邮箱地址。请告诉我收件人邮箱，例如：发送给 ops@example.com。",
                "missing_recipients",
            )

        missing_config = self._missing_smtp_config()
        if missing_config:
            return self._failed(
                "邮件发送失败：SMTP 配置不完整，请先在 .env 中补充邮件服务器配置。",
                "missing_smtp_config",
                missing_config=missing_config,
            )

        attachments, attachment_error = self._collect_attachments(tool_input)
        if attachment_error:
            return self._failed(attachment_error, "invalid_attachments")

        subject = self._clean_header(params.get("subject") or self._default_subject(context))
        body = str(params.get("body") or params.get("content") or params.get("message") or tool_input.query).strip()
        if not body:
            body = "SkyGuard 灾害分析通知，请查看附件或任务详情。"

        try:
            message = self._build_message(
                recipients=recipients,
                cc=cc,
                subject=subject,
                body=body,
                html_body=params.get("html_body"),
                attachments=attachments,
            )
            all_recipients = recipients + cc + bcc
            self._send(message, all_recipients)
        except (OSError, smtplib.SMTPException) as exc:
            return self._failed(
                f"邮件发送失败：SMTP 服务调用异常：{exc}",
                "smtp_error",
                error=str(exc),
            )

        attachment_artifacts = [
            ArtifactItem(type="email_attachment", path=str(path), metadata={"filename": path.name})
            for path in attachments
        ]
        recipient_text = "、".join(recipients)
        return ToolResult(
            summary=f"【邮件通知】已通过 SMTP 发送给 {len(recipients)} 个收件人：{recipient_text}",
            evidence=[
                EvidenceItem(
                    source="email",
                    type="notification",
                    content=f"邮件主题《{subject}》已发送，收件人：{recipient_text}",
                    confidence=1.0,
                )
            ],
            artifacts=attachment_artifacts,
            confidence=1.0,
            data={
                "email_status": "sent",
                "recipients": recipients,
                "cc": cc,
                "bcc_count": len(bcc),
                "subject": subject,
                "attachments": [str(path) for path in attachments],
            },
        )

    def _send(self, message: EmailMessage, recipients: list[str]) -> None:
        host = settings.SMTP_HOST
        port = settings.SMTP_PORT
        timeout = settings.SMTP_TIMEOUT_SECONDS
        from_address = self._from_address()

        smtp_cls = self._smtp_ssl_factory if settings.SMTP_USE_SSL else self._smtp_factory
        with smtp_cls(host, port, timeout=timeout) as smtp:
            if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
                smtp.starttls()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message, from_addr=from_address, to_addrs=recipients)

    def _build_message(
        self,
        recipients: list[str],
        cc: list[str],
        subject: str,
        body: str,
        html_body: Any,
        attachments: list[Path],
    ) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((settings.SMTP_FROM_NAME, self._from_address()))
        message["To"] = ", ".join(recipients)
        if cc:
            message["Cc"] = ", ".join(cc)
        message["Subject"] = subject
        message.set_content(body)

        if html_body:
            message.add_alternative(str(html_body), subtype="html")

        for path in attachments:
            content_type, _ = mimetypes.guess_type(path.name)
            if content_type:
                maintype, subtype = content_type.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"
            message.add_attachment(
                path.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )

        return message

    def _collect_recipients(
        self,
        params: dict[str, Any],
        query: str,
        *keys: str,
    ) -> tuple[list[str], list[str]]:
        raw_values: list[Any] = []
        for key in keys:
            if key in params:
                raw_values.append(params[key])

        if not raw_values and query:
            raw_values.extend(EMAIL_PATTERN.findall(query))

        addresses: list[str] = []
        invalid: list[str] = []
        for item in self._flatten(raw_values):
            if isinstance(item, dict):
                item = item.get("email") or item.get("address") or item.get("to")
            if item is None:
                continue
            parsed = getaddresses([str(item)])
            if not parsed and str(item).strip():
                invalid.append(str(item))
            for _, address in parsed:
                address = address.strip()
                if not address:
                    continue
                if EMAIL_PATTERN.fullmatch(address):
                    addresses.append(address)
                else:
                    invalid.append(address)

        return list(dict.fromkeys(addresses)), list(dict.fromkeys(invalid))

    def _collect_attachments(self, tool_input: ToolInput) -> tuple[list[Path], str | None]:
        raw_values: list[Any] = []
        params = tool_input.params or {}
        for key in ("attachments", "attachment_paths", "file_paths", "report_path"):
            if key in params:
                raw_values.append(params[key])
        for file_info in tool_input.files:
            raw_values.append(file_info.get("path") or file_info.get("file_path"))

        paths: list[Path] = []
        for item in self._flatten(raw_values):
            if isinstance(item, dict):
                item = item.get("path") or item.get("file_path")
            if item is None or str(item).strip() == "":
                continue
            path = Path(str(item)).expanduser()
            if not path.exists():
                return [], f"邮件发送失败：附件不存在：{path}"
            if not path.is_file():
                return [], f"邮件发送失败：附件不是文件：{path}"
            paths.append(path.resolve())

        return list(dict.fromkeys(paths)), None

    def _missing_smtp_config(self) -> list[str]:
        missing = []
        if not settings.SMTP_HOST:
            missing.append("SMTP_HOST")
        if not self._from_address():
            missing.append("SMTP_FROM")
        if settings.SMTP_USERNAME and not settings.SMTP_PASSWORD:
            missing.append("SMTP_PASSWORD")
        if settings.SMTP_PASSWORD and not settings.SMTP_USERNAME:
            missing.append("SMTP_USERNAME")
        return missing

    def _from_address(self) -> str:
        return (settings.SMTP_FROM or settings.SMTP_USERNAME or "").strip()

    def _default_subject(self, context: ToolContext | None) -> str:
        if context and context.task_id is not None:
            return f"SkyGuard 任务 {context.task_id} 灾害分析通知"
        return "SkyGuard 灾害分析通知"

    def _clean_header(self, value: Any) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        return text or "SkyGuard 灾害分析通知"

    def _needs_user_input(self, summary: str, reason: str, **extra: Any) -> ToolResult:
        return ToolResult(
            summary=summary,
            confidence=0.0,
            need_user_confirm=True,
            data={"email_status": "failed", "reason": reason, **extra},
        )

    def _failed(self, summary: str, reason: str, **extra: Any) -> ToolResult:
        return ToolResult(
            summary=summary,
            confidence=0.0,
            data={"email_status": "failed", "reason": reason, **extra},
        )

    def _flatten(self, values: Iterable[Any]) -> Iterable[Any]:
        for value in values:
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                yield from self._flatten(value)
            else:
                yield value
