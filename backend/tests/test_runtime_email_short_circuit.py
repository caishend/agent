import unittest
from unittest.mock import patch

from app.agent.runtime import iter_agent_events, session_store


class RuntimeEmailShortCircuitTest(unittest.TestCase):
    def tearDown(self):
        session_store.clear(901)

    def test_missing_email_recipient_returns_prompt_without_llm(self):
        with patch("app.agent.runtime.stream_llm_answer") as stream_llm_answer:
            events = list(
                iter_agent_events(
                    task_id=901,
                    user_id=1,
                    message="把报告发送出去",
                    files=[],
                    params={"forced_tool": "email"},
                )
            )

        event_types = [event.get("type") for event in events]
        answers = [event.get("content") for event in events if event.get("type") == "answer"]

        self.assertIn("tool_result", event_types)
        self.assertNotIn("llm_call", event_types)
        self.assertTrue(any("邮箱" in str(answer) for answer in answers))
        stream_llm_answer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
