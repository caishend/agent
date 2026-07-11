import unittest
from unittest.mock import patch

from app.agent.runtime import iter_agent_events, session_store
from app.agent.tools.base_tool import ToolResult


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

    def test_llm_fallback_is_also_emitted_as_answer_delta_events(self):
        with patch("app.agent.runtime.stream_llm_answer", side_effect=RuntimeError("offline")), patch(
            "app.agent.runtime.synthesize_answer",
            return_value="fallback answer",
        ):
            events = list(
                iter_agent_events(
                    task_id=902,
                    user_id=1,
                    message="question",
                    files=[],
                    params={"disable_llm_router": True},
                )
            )

        deltas = [event["content"] for event in events if event.get("type") == "answer_delta"]
        final_answers = [event["content"] for event in events if event.get("type") == "answer"]

        self.assertEqual("".join(deltas), "fallback answer")
        self.assertEqual(final_answers[-1], "fallback answer")

    def test_disaster_analysis_does_not_request_report_format(self):
        fake_result = ToolResult(
            summary="ok",
            data={"assessment_status": "completed", "assessment": {}},
            confidence=0.9,
        )
        with patch("app.agent.runtime.call_tool", return_value=fake_result), patch(
            "app.agent.runtime.stream_llm_answer",
            return_value=iter(["完成分析"]),
        ):
            events = list(
                iter_agent_events(
                    task_id=902,
                    user_id=1,
                    message="成都暴雨灾害评估",
                    files=[],
                    params={"forced_tool": "disaster_analysis", "disable_llm_router": True},
                )
            )

        self.assertFalse(any(event.get("type") == "report_format_required" for event in events))
        self.assertEqual(
            [event.get("tool") for event in events if event.get("type") == "tool_call"],
            ["browser", "graphrag", "risk_assessment"],
        )

    def test_report_generation_requests_format_before_running_tool(self):
        events = list(
            iter_agent_events(
                task_id=902,
                user_id=1,
                message="生成成都暴雨灾害评估报告",
                files=[],
                params={"forced_tool": "report", "disable_llm_router": True},
            )
        )

        self.assertTrue(any(event.get("type") == "report_format_required" for event in events))
        self.assertFalse(any(event.get("type") == "tool_call" and event.get("tool") == "report" for event in events))


if __name__ == "__main__":
    unittest.main()
