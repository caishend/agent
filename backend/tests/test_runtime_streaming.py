import unittest
from unittest.mock import patch

from app.agent.runtime import iter_agent_events, session_store


class RuntimeStreamingTest(unittest.TestCase):
    def tearDown(self):
        session_store.clear(902)

    def test_llm_chunks_are_emitted_as_answer_delta_events(self):
        with patch("app.agent.runtime.stream_llm_answer", return_value=iter(["第一段", "第二段"])):
            events = list(
                iter_agent_events(
                    task_id=902,
                    user_id=1,
                    message="普通问题",
                    files=[],
                    params={"disable_llm_router": True},
                )
            )

        deltas = [event["content"] for event in events if event.get("type") == "answer_delta"]
        final_answers = [event["content"] for event in events if event.get("type") == "answer"]

        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual("".join(deltas), "第一段第二段")
        self.assertEqual(final_answers[-1], "第一段第二段")


if __name__ == "__main__":
    unittest.main()
