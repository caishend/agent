"""LLM clients used by the agent runtime."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import httpx

from app.agent.tools.base_tool import ToolResult
from app.config import settings


class LLMUnavailableError(RuntimeError):
    """Raised when no LLM backend is configured or reachable."""


def is_llm_configured() -> bool:
    return bool(settings.OPENAI_API_KEY and settings.LLM_MODEL)


def complete_llm_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.0,
    timeout: float = 45.0,
) -> dict[str, Any]:
    text = complete_llm_text(
        system_prompt,
        user_prompt,
        temperature=temperature,
        timeout=timeout,
        response_format={"type": "json_object"},
    )
    return _parse_json_object(text)


def complete_llm_text(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
    timeout: float = 60.0,
    response_format: dict[str, Any] | None = None,
) -> str:
    if not is_llm_configured():
        raise LLMUnavailableError("LLM 未配置：请设置 OPENAI_API_KEY 和 LLM_MODEL")

    payload: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "temperature": temperature,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if response_format:
        payload["response_format"] = response_format

    data = _post_chat_completion(payload, timeout=timeout)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise LLMUnavailableError("LLM 返回为空")
    return content


def stream_llm_answer(
    message: str,
    results: dict[str, ToolResult],
    metadata: dict[str, Any],
) -> Iterator[str]:
    if not is_llm_configured():
        raise LLMUnavailableError("LLM 未配置：请设置 OPENAI_API_KEY 和 LLM_MODEL")
    yield from _stream_with_httpx(message, results, metadata)


def _stream_with_httpx(
    message: str,
    results: dict[str, ToolResult],
    metadata: dict[str, Any],
) -> Iterator[str]:
    payload = {
        "model": settings.LLM_MODEL,
        "temperature": 0.2,
        "stream": True,
        "messages": [
            {"role": "system", "content": _answer_system_prompt()},
            {"role": "user", "content": _answer_user_prompt(message, results, metadata)},
        ],
    }

    with httpx.stream(
        "POST",
        _chat_completion_url(),
        headers=_auth_headers(),
        json=payload,
        timeout=60,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = event.get("choices", [{}])[0].get("delta", {})
            text = _normalize_chunk_content(delta.get("content", ""))
            if text:
                yield text


def _post_chat_completion(payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    response = httpx.post(
        _chat_completion_url(),
        headers=_auth_headers(),
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _chat_completion_url() -> str:
    return f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _answer_system_prompt() -> str:
    return (
        "你是 SkyGuard 灾害智能分析平台的专业 Agent。"
        "你必须基于工具结果、对话历史和已知上下文回答。"
        "conversation_history 是同一任务下最近对话，必须用于回答身份、偏好、前文指代等记忆问题。"
        "如果信息不足，要明确说明缺口；禁止编造不存在的事实。"
        "回答使用 Markdown，结构清晰、简洁、专业。"
    )


def _answer_user_prompt(
    message: str,
    results: dict[str, ToolResult],
    metadata: dict[str, Any],
) -> str:
    payload = {
        "user_question": message,
        "conversation_history": metadata.get("conversation_history", []),
        "tool_results": {
            name: result.to_dict()
            for name, result in results.items()
        },
        "session_memory": {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "formal_memory",
                "last_draft",
                "risk_assessment",
                "last_report_path",
                "confirmed_task",
                "conversation_record",
            }
        },
    }
    return (
        "请根据下面 JSON 上下文生成最终回复。"
        "如果用户问“我是谁”“我刚才说了什么”等问题，优先从 conversation_history 中找答案。"
        "如果 conversation_history 里有用户自述姓名或偏好，应该承认并复述；不要要求用户重新登录。\n"
        f"{_safe_json(payload)}"
    )


def _safe_json(payload: dict[str, Any], limit: int = 24000) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...（上下文过长，已截断）"


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM JSON 响应不是对象")
    return value


def _normalize_chunk_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""
