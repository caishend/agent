"""Email notification tool."""
from __future__ import annotations

import mimetypes
import json
import re
import smtplib
from collections.abc import Callable, Iterable
from email.message import EmailMessage
from email.utils import formataddr, getaddresses
from pathlib import Path
from typing import Any

from app.agent.llm import complete_llm_json
from app.agent.tools.base_tool import ArtifactItem, BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult
from app.config import settings


EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?![\w.+-])",
    re.ASCII,
)


class EmailTool(BaseTool):
    name = "email"
    description = "通过 SMTP 将报告、预警结论或通知发送到指定邮箱。默认先生成草稿，用户确认后才真正发送。"

    def __init__(
        self,
        smtp_factory: Callable[..., Any] | None = None,
        smtp_ssl_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._smtp_factory = smtp_factory or smtplib.SMTP
        self._smtp_ssl_factory = smtp_ssl_factory or smtplib.SMTP_SSL

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        params = tool_input.params or {}
        draft_from_params = params.get("email_draft") if isinstance(params.get("email_draft"), dict) else {}

        recipients, invalid_recipients = self._collect_recipients(
            params,
            tool_input.query,
            "recipients",
            "to",
        )
        cc, invalid_cc = self._collect_recipients(params, "", "cc")
        bcc, invalid_bcc = self._collect_recipients(params, "", "bcc")
        if draft_from_params:
            recipients = recipients or self._as_string_list(draft_from_params.get("recipients"))
            cc = cc or self._as_string_list(draft_from_params.get("cc"))
            bcc = bcc or self._as_string_list(draft_from_params.get("bcc"))

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

        attachments, attachment_error = self._collect_attachments(tool_input)
        if attachment_error:
            return self._failed(attachment_error, "invalid_attachments")

        subject, body, draft_source = self._compose_draft_content(
            tool_input=tool_input,
            context=context,
            params=params,
            draft_from_params=draft_from_params,
            attachments=attachments,
        )

        draft = {
            "recipients": recipients,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body": body,
            "draft_source": draft_source,
            "attachments": [str(path) for path in attachments],
            "attachment_names": [path.name for path in attachments],
        }

        if not self._is_confirmed(params):
            return self._draft_result(draft)

        missing_config = self._missing_smtp_config()
        if missing_config:
            return self._failed(
                "邮件发送失败：SMTP 配置不完整，请先在 .env 中补充邮件服务器配置。",
                "missing_smtp_config",
                missing_config=missing_config,
            )

        try:
            message = self._build_message(
                recipients=recipients,
                cc=cc,
                subject=subject,
                body=body,
                html_body=params.get("html_body") or draft_from_params.get("html_body"),
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

    def _draft_result(self, draft: dict[str, Any]) -> ToolResult:
        attachment_text = "、".join(draft["attachment_names"]) if draft["attachment_names"] else "无"
        cc_text = f"\n- 抄送：{'、'.join(draft['cc'])}" if draft["cc"] else ""
        bcc_text = f"\n- 密送：{len(draft['bcc'])} 个收件人" if draft["bcc"] else ""
        summary = (
            "请确认是否发送以下邮件：\n\n"
            f"- 收件人：{'、'.join(draft['recipients'])}"
            f"{cc_text}{bcc_text}\n"
            f"- 主题：{draft['subject']}\n"
            f"- 附件：{attachment_text}\n\n"
            f"正文预览：\n{draft['body'][:1000]}"
        )
        return ToolResult(
            summary=summary,
            confidence=1.0,
            need_user_confirm=True,
            data={"email_status": "pending_confirmation", "email_draft": draft},
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
        draft = params.get("email_draft") if isinstance(params.get("email_draft"), dict) else {}
        for key in ("attachments", "attachment_paths", "file_paths", "report_path"):
            if key in params:
                raw_values.append(params[key])
        if draft.get("attachments"):
            raw_values.append(draft["attachments"])
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



    def _compose_draft_content(
        self,
        *,
        tool_input: ToolInput,
        context: ToolContext | None,
        params: dict[str, Any],
        draft_from_params: dict[str, Any],
        attachments: list[Path],
    ) -> tuple[str, str, str]:
        explicit_subject = (
            params.get("subject")
            or draft_from_params.get("subject")
            or self._extract_labeled_value(tool_input.query, ("\u90ae\u4ef6\u4e3b\u9898", "\u4e3b\u9898", "subject"))
        )
        explicit_body = (
            params.get("body")
            or params.get("content")
            or params.get("message")
            or draft_from_params.get("body")
            or self._extract_labeled_value(tool_input.query, ("\u90ae\u4ef6\u6b63\u6587", "\u6b63\u6587", "\u90ae\u4ef6\u5185\u5bb9", "\u5185\u5bb9", "body"))
        )

        subject = self._clean_header(explicit_subject or "")
        body = str(explicit_body or "").strip()
        has_explicit_subject = bool(str(explicit_subject or "").strip())
        has_explicit_body = bool(body)
        if has_explicit_subject and has_explicit_body:
            return subject, body, "user_specified"

        generated = self._generate_email_draft_with_llm(
            query=tool_input.query,
            context=context,
            attachments=attachments,
            subject_hint=subject,
            body_hint=body,
        )
        if generated:
            return (
                self._clean_header(subject or generated.get("subject") or self._default_subject(context)),
                str(body or generated.get("body") or "").strip() or self._fallback_body(context, attachments),
                "llm_generated",
            )

        return (
            self._clean_header(subject or self._default_subject(context)),
            body or self._fallback_body(context, attachments),
            "template_fallback",
        )

    def _generate_email_draft_with_llm(
        self,
        *,
        query: str,
        context: ToolContext | None,
        attachments: list[Path],
        subject_hint: str,
        body_hint: str,
    ) -> dict[str, Any] | None:
        metadata = context.metadata if context else {}
        payload = {
            "user_request": query,
            "task_id": context.task_id if context else None,
            "subject_hint": subject_hint,
            "body_hint": body_hint,
            "attachment_names": [path.name for path in attachments],
            "last_report_path": metadata.get("last_report_path"),
            "conversation_record": str(metadata.get("conversation_record") or "")[-4000:],
            "formal_memory": metadata.get("formal_memory") or {},
            "risk_assessment": metadata.get("risk_assessment") or {},
        }
        system_prompt = (
            "\u4f60\u662f SkyGuard \u707e\u5bb3\u667a\u80fd\u5206\u6790\u5e73\u53f0\u7684\u90ae\u4ef6\u79d8\u4e66\uff0c\u53ea\u8f93\u51fa JSON\u3002"
            "\u8bf7\u6839\u636e\u7528\u6237\u8bf7\u6c42\u3001\u4efb\u52a1\u4e0a\u4e0b\u6587\u548c\u9644\u4ef6\u751f\u6210\u4e00\u5c01\u6b63\u5f0f\u3001\u7b80\u6d01\u3001\u81ea\u7136\u7684\u4e2d\u6587\u90ae\u4ef6\u8349\u7a3f\u3002"
            "\u4e0d\u8981\u628a\u7528\u6237\u539f\u8bdd\u76f4\u63a5\u5f53\u6b63\u6587\uff1b\u5982\u679c\u7528\u6237\u660e\u786e\u6307\u5b9a\u4e3b\u9898\u6216\u6b63\u6587\uff0c\u5fc5\u987b\u4f18\u5148\u4fdd\u7559\u3002"
            "\u6b63\u6587\u5e94\u5305\u542b\u95ee\u5019\u3001\u53d1\u9001\u76ee\u7684\u3001\u9644\u4ef6\u8bf4\u660e\u3001\u67e5\u9605\u5efa\u8bae\u548c\u843d\u6b3e\u3002"
            "JSON \u5b57\u6bb5\u5fc5\u987b\u4e3a subject \u548c body\u3002"
        )
        try:
            draft = complete_llm_json(
                system_prompt,
                json.dumps(payload, ensure_ascii=False, default=str),
                temperature=0.2,
                timeout=30,
            )
        except Exception:
            return None
        subject = str(draft.get("subject") or "").strip()
        body = str(draft.get("body") or "").strip()
        if not subject and not body:
            return None
        return {"subject": subject, "body": body}

    def _extract_labeled_value(self, query: str, labels: tuple[str, ...]) -> str:
        text = str(query or "").strip()
        if not text:
            return ""
        label_pattern = "|".join(re.escape(label) for label in labels)
        stop_labels = "\u90ae\u4ef6\u4e3b\u9898|\u4e3b\u9898|subject|\u90ae\u4ef6\u6b63\u6587|\u6b63\u6587|\u90ae\u4ef6\u5185\u5bb9|\u5185\u5bb9|body|\u90ae\u7bb1|\u6536\u4ef6\u4eba|\u9644\u4ef6"
        pattern = rf"(?:{label_pattern})\s*(?:\u662f|\u4e3a|:|\uff1a)?\s*(.+?)(?=(?:[,\uff0c\u3002\uff1b;]\s*(?:{stop_labels})\s*(?:\u662f|\u4e3a|:|\uff1a)?)|$)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        value = match.group(1).strip(" ,\uff0c\u3002\uff1b;\n\t")
        return EMAIL_PATTERN.sub("", value).strip(" ,\uff0c\u3002\uff1b;\n\t")

    def _fallback_body(self, context: ToolContext | None, attachments: list[Path]) -> str:
        task_text = f"\u4efb\u52a1 {context.task_id}" if context and context.task_id is not None else "\u76f8\u5173\u4efb\u52a1"
        attachment_text = "\u3001".join(path.name for path in attachments) or "\u76f8\u5173\u6750\u6599"
        return (
            "\u60a8\u597d\uff1a\n\n"
            f"\u73b0\u5c06 SkyGuard \u5e73\u53f0\u751f\u6210\u7684{task_text}\u707e\u5bb3\u5206\u6790\u6750\u6599\u53d1\u9001\u7ed9\u60a8\uff0c\u8bf7\u67e5\u6536\u9644\u4ef6\uff1a{attachment_text}\u3002\n\n"
            "\u9644\u4ef6\u5185\u5bb9\u53ef\u7528\u4e8e\u4e86\u89e3\u707e\u5bb3\u4e8b\u4ef6\u6982\u51b5\u3001\u98ce\u9669\u5224\u65ad\u3001\u5f71\u54cd\u8303\u56f4\u53ca\u5904\u7f6e\u5efa\u8bae\u3002\u5982\u9700\u8fdb\u4e00\u6b65\u6838\u67e5\uff0c\u8bf7\u7ed3\u5408\u5f53\u5730\u5b98\u65b9\u9884\u8b66\u3001\u5e94\u6025\u901a\u62a5\u548c\u73b0\u573a\u4fe1\u606f\u8fdb\u884c\u786e\u8ba4\u3002\n\n"
            "\u6b64\u81f4\n"
            "SkyGuard \u707e\u5bb3\u667a\u80fd\u5206\u6790\u5e73\u53f0"
        )

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

    def _is_confirmed(self, params: dict[str, Any]) -> bool:
        return bool(params.get("confirm_email") or params.get("confirmed_email") or params.get("email_confirmed"))

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

    def _as_string_list(self, value: Any) -> list[str]:
        return [str(item).strip() for item in self._flatten([value]) if str(item).strip()]

    def _flatten(self, values: Iterable[Any]) -> Iterable[Any]:
        for value in values:
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                yield from self._flatten(value)
            else:
                yield value
