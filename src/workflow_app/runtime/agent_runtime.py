#!/usr/bin/env python3
"""Real agent runtime client.

Supports OpenAI-compatible /chat/completions API only.
No mock fallback is provided here by design.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Callable


class AgentConfigError(RuntimeError):
    pass


class AgentRuntimeError(RuntimeError):
    pass


@dataclass
class AgentConfig:
    base_url: str
    api_key: str
    model: str
    timeout_s: float = 120.0
    temperature: float = 0.2


def load_agent_config_from_env() -> AgentConfig:
    # OpenAI-compatible endpoint. Example:
    # WORKFLOW_AGENT_BASE_URL=https://api.openai.com/v1
    base_url = (os.getenv("WORKFLOW_AGENT_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("WORKFLOW_AGENT_API_KEY") or "").strip()
    model = (os.getenv("WORKFLOW_AGENT_MODEL") or "").strip()

    if not base_url or not api_key or not model:
        raise AgentConfigError(
            "real agent is not configured. set WORKFLOW_AGENT_BASE_URL, "
            "WORKFLOW_AGENT_API_KEY, WORKFLOW_AGENT_MODEL"
        )
    return AgentConfig(base_url=base_url, api_key=api_key, model=model)


def _request_json(
    config: AgentConfig,
    payload: dict,
    stream: bool,
) -> urllib.request.Request:
    body = dict(payload)
    body["model"] = config.model
    body["temperature"] = config.temperature
    body["stream"] = bool(stream)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
    )
    return req


def _parse_non_stream_response(raw: bytes) -> str:
    try:
        obj = json.loads(raw.decode("utf-8"))
        choice = (obj.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    except Exception as exc:
        raise AgentRuntimeError(f"invalid non-stream response: {exc}") from exc
    raise AgentRuntimeError("empty non-stream response content")


def chat_once(messages: list[dict[str, str]]) -> str:
    config = load_agent_config_from_env()
    payload = {"messages": messages}
    req = _request_json(config, payload=payload, stream=False)
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:
            raw = resp.read()
        return _parse_non_stream_response(raw)
    except Exception as exc:
        raise AgentRuntimeError(str(exc)) from exc


def stream_chat(
    messages: list[dict[str, str]],
    on_delta: Callable[[str], None],
    should_stop: Callable[[], bool],
) -> str:
    config = load_agent_config_from_env()
    payload = {"messages": messages}
    req = _request_json(config, payload=payload, stream=True)

    full = []
    try:
        with urllib.request.urlopen(req, timeout=config.timeout_s) as resp:
            while True:
                if should_stop():
                    break
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if not text.startswith("data: "):
                    continue
                data_text = text[6:].strip()
                if data_text == "[DONE]":
                    break
                try:
                    obj = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                delta = ""
                choices = obj.get("choices") or []
                if choices:
                    delta_obj = choices[0].get("delta") or {}
                    delta = delta_obj.get("content") or ""
                if delta:
                    full.append(delta)
                    on_delta(delta)
    except Exception as exc:
        raise AgentRuntimeError(str(exc)) from exc
    return "".join(full)

