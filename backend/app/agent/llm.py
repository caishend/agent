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
    yielded_content = False
    try:
        for chunk in _stream_with_langchain(message, results, metadata):
            yielded_content = True
            yield chunk
    except Exception:
        if yielded_content:
            raise
        yield from _stream_with_httpx(message, results, metadata)


def _stream_with_langchain(
    message: str,
    results: dict[str, ToolResult],
    metadata: dict[str, Any],
) -> Iterator[str]:
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise LLMUnavailableError("LangChain 流式依赖未安装") from exc

    llm = ChatOpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0.2,
        streaming=True,
        timeout=60,
        max_retries=0,
    )
    messages = [
        SystemMessage(content=_answer_system_prompt()),
        HumanMessage(content=_answer_user_prompt(message, results, metadata)),
    ]
    for chunk in llm.stream(messages):
        text = _normalize_chunk_content(getattr(chunk, "content", ""))
        if text:
            yield text


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
        "如果工具结果包含 risk_assessment，最终回复必须明确写出风险等级、风险评分、评估依据和处置建议。"
        "回答使用 Markdown，结构清晰、简洁、专业。"
    )


def _answer_user_prompt(
    message: str,
    results: dict[str, ToolResult],
    metadata: dict[str, Any],
) -> str:
    payload = {
        "user_question": message,
        "conversation_history": _compact_conversation_history(metadata.get("conversation_history", [])),
        "tool_results": {
            name: _compact_tool_result(name, result)
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
        "如果 tool_results.risk_assessment 存在，必须保留其中的 risk_level、risk_score、basis、risk_factors 和 suggestions，不要只泛泛总结。\n"
        f"{_safe_json(payload)}"
    )


def _compact_conversation_history(history: Any, *, max_items: int = 8, content_limit: int = 500) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in history[-max_items:]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "role": item.get("role"),
                "content": _shorten_text(item.get("content"), content_limit),
                "created_at": item.get("created_at"),
            }
        )
    return compact


def _compact_tool_result(name: str, result: ToolResult) -> dict[str, Any]:
    evidence_limit = 5 if name == "browser" else 6
    content_limit = 360 if name == "browser" else 520
    compact = {
        "summary": _shorten_text(result.summary, 1200),
        "need_user_confirm": result.need_user_confirm,
        "evidence": [
            {
                "source": item.source,
                "type": item.type,
                "content": _shorten_text(item.content, content_limit),
                "metadata": _compact_metadata(item.metadata),
            }
            for item in result.evidence[:evidence_limit]
        ],
        "artifacts": [
            {
                "type": item.type,
                "path": item.path,
                "metadata": _compact_metadata(item.metadata),
            }
            for item in result.artifacts[:8]
        ],
    }
    tool_data = _compact_tool_data(name, result.data)
    if tool_data:
        compact["data"] = tool_data
    return compact


def _compact_tool_data(name: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if name == "browser":
        return {
            key: value
            for key, value in {
                "search_mode": data.get("search_mode"),
                "query": data.get("query"),
                "screenshot_observations": [
                    _shorten_text(item, 220)
                    for item in (data.get("screenshot_observations") or [])[:5]
                ],
            }.items()
            if value
        }
    if name == "document":
        return {
            key: value
            for key, value in {
                "document_mode": data.get("document_mode"),
                "key_points": [_shorten_text(item, 260) for item in (data.get("key_points") or [])[:8]],
                "graph_rag_ready": data.get("graph_rag_ready"),
            }.items()
            if value not in (None, [], "")
        }
    if name == "graphrag":
        return {
            key: value
            for key, value in {
                "retrieval_mode": data.get("retrieval_mode"),
                "needs_web_search": data.get("needs_web_search"),
                "reasoning_paths": [
                    _shorten_text(item, 320)
                    for item in (data.get("reasoning_paths") or [])[:6]
                ],
            }.items()
            if value not in (None, [], "")
        }
    return {
        key: _shorten_text(value, 800) if isinstance(value, str) else value
        for key, value in data.items()
        if key not in {"documents", "search_results", "raw", "raw_results", "pages"}
    }


def _compact_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    allowed_keys = ("url", "source", "path", "site_name", "date_published", "chunk_index", "rag_score")
    return {
        key: _shorten_text(value, 220) if isinstance(value, str) else value
        for key, value in metadata.items()
        if key in allowed_keys and value not in (None, "")
    }


def _safe_json(payload: dict[str, Any], limit: int = 14000) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...（上下文过长，已截断）"


def _shorten_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


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
