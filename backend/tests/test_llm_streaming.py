import unittest
from unittest.mock import patch

from app.agent.llm import stream_llm_answer


class LLMStreamingTest(unittest.TestCase):
    @patch("app.agent.llm.is_llm_configured", return_value=True)
    @patch("app.agent.llm._stream_with_httpx", return_value=iter(["fallback"]))
    @patch("app.agent.llm._stream_with_langchain", side_effect=RuntimeError("unavailable"))
    def test_uses_http_fallback_before_any_content(self, _langchain, _httpx, _configured):
        self.assertEqual(list(stream_llm_answer("question", {}, {})), ["fallback"])

    @patch("app.agent.llm.is_llm_configured", return_value=True)
    @patch("app.agent.llm._stream_with_httpx", return_value=iter(["duplicate"]))
    @patch("app.agent.llm._stream_with_langchain")
    def test_does_not_restart_after_partial_content(self, langchain, httpx_fallback, _configured):
        def partial_stream(*_args):
            yield "partial"
            raise RuntimeError("connection lost")

        langchain.side_effect = partial_stream
        stream = stream_llm_answer("question", {}, {})

        self.assertEqual(next(stream), "partial")
        with self.assertRaisesRegex(RuntimeError, "connection lost"):
            next(stream)
        httpx_fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
