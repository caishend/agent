import unittest

from app.agent.tools.base_tool import ToolContext, ToolInput
from app.agent.tools.email import EmailTool
from app.config import settings


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.sent_messages = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.sent_messages.append(
            {
                "message": message,
                "from_addr": from_addr,
                "to_addrs": to_addrs,
            }
        )


class EmailToolTest(unittest.TestCase):
    SMTP_FIELDS = (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SMTP_FROM_NAME",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
        "SMTP_TIMEOUT_SECONDS",
    )

    def setUp(self):
        self._old_settings = {field: getattr(settings, field) for field in self.SMTP_FIELDS}
        FakeSMTP.instances.clear()

    def tearDown(self):
        for field, value in self._old_settings.items():
            setattr(settings, field, value)
        FakeSMTP.instances.clear()

    def test_missing_recipients_asks_user_for_recipient(self):
        self._configure_smtp()

        result = EmailTool(smtp_factory=FakeSMTP).run(
            ToolInput(query="请发送灾害预警邮件"),
            ToolContext(task_id=1),
        )

        self.assertEqual(result.data["email_status"], "failed")
        self.assertEqual(result.data["reason"], "missing_recipients")
        self.assertTrue(result.need_user_confirm)
        self.assertIn("邮箱", result.summary)
        self.assertEqual(FakeSMTP.instances, [])

    def test_missing_smtp_config_returns_failed_tool_result(self):
        settings.SMTP_HOST = ""
        settings.SMTP_FROM = ""
        settings.SMTP_USERNAME = ""
        settings.SMTP_PASSWORD = ""

        result = EmailTool(smtp_factory=FakeSMTP).run(
            ToolInput(query="请发送给 ops@example.com"),
            ToolContext(task_id=1),
        )

        self.assertEqual(result.data["email_status"], "failed")
        self.assertEqual(result.data["reason"], "missing_smtp_config")
        self.assertIn("SMTP_HOST", result.data["missing_config"])
        self.assertIn("SMTP_FROM", result.data["missing_config"])
        self.assertEqual(FakeSMTP.instances, [])

    def test_sends_email_through_configured_smtp(self):
        self._configure_smtp()
        tool = EmailTool(smtp_factory=FakeSMTP)

        result = tool.run(
            ToolInput(
                query="发送预警",
                params={
                    "recipients": ["ops@example.com"],
                    "subject": "洪水预警",
                    "body": "请查看最新灾害分析结论。",
                },
            ),
            ToolContext(task_id=9),
        )

        self.assertEqual(result.data["email_status"], "sent")
        self.assertEqual(result.data["recipients"], ["ops@example.com"])

        smtp = FakeSMTP.instances[0]
        self.assertEqual(smtp.host, "smtp.example.com")
        self.assertEqual(smtp.port, 587)
        self.assertTrue(smtp.started_tls)
        self.assertEqual(smtp.login_args, ("noreply@example.com", "secret"))

        sent = smtp.sent_messages[0]
        message = sent["message"]
        self.assertEqual(sent["from_addr"], "noreply@example.com")
        self.assertEqual(sent["to_addrs"], ["ops@example.com"])
        self.assertEqual(message["To"], "ops@example.com")
        self.assertEqual(message["Subject"], "洪水预警")
        self.assertIn("请查看最新灾害分析结论。", message.get_content())

    def _configure_smtp(self):
        settings.SMTP_HOST = "smtp.example.com"
        settings.SMTP_PORT = 587
        settings.SMTP_USERNAME = "noreply@example.com"
        settings.SMTP_PASSWORD = "secret"
        settings.SMTP_FROM = "noreply@example.com"
        settings.SMTP_FROM_NAME = "SkyGuard"
        settings.SMTP_USE_TLS = True
        settings.SMTP_USE_SSL = False
        settings.SMTP_TIMEOUT_SECONDS = 10.0


if __name__ == "__main__":
    unittest.main()
