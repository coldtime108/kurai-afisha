"""Bounded NVIDIA transport. Credentials and provider responses never enter logs."""

import asyncio
import json
import os
from dataclasses import dataclass, field

import httpx

MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    model: str = MODEL
    timeout: float = 7.0
    daily_calls: int | None = None
    daily_tokens: int | None = None

    @classmethod
    def from_env(cls):
        # No automatic paid fallback, arbitrary endpoint, or browser-side key.
        return cls(
            enabled=os.getenv("LLM_ENABLED", "false").lower() == "true",
            api_key=os.getenv("NVIDIA_API_KEY", ""),
            model=os.getenv("LLM_MODEL", MODEL),
            timeout=7.0,
        )

    @property
    def ready(self):
        return self.enabled and bool(self.api_key) and self.model == MODEL


class NvidiaProvider:
    def __init__(self, settings=None, transport=None):
        self.settings = settings or LLMSettings.from_env()
        self.transport = transport

    @property
    def ready(self):
        return self.settings.ready

    def complete(self, messages, tools, timeout):
        if not self.ready:
            raise ProviderError("disabled")
        try:
            return asyncio.run(self._complete(messages, tools, timeout))
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderError("timeout") from None
        except ProviderError:
            raise
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ):
            raise ProviderError("invalid_response") from None

    async def _complete(self, messages, tools, timeout):
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "reasoning_effort": "none",
            "temperature": 0.2,
            "max_tokens": 768,
            "stream": False,
        }
        async with asyncio.timeout(min(timeout, self.settings.timeout)):
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=httpx.Timeout(min(timeout, self.settings.timeout), connect=3),
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    ENDPOINT,
                    json=payload,
                    headers={"Authorization": "Bearer " + self.settings.api_key},
                ) as response:
                    if response.status_code != 200:
                        raise ProviderError(
                            {429: "rate_limited", 451: "access_restricted"}.get(
                                response.status_code, "provider_unavailable"
                            )
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 128_000:
                            raise ProviderError("response_too_large")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ProviderError("invalid_response")
            choice = body["choices"][0]
            usage = body.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            # Discard raw prose and reasoning; only validated tool arguments are used.
            return {
                "calls": choice["message"].get("tool_calls", []),
                "finish_reason": choice.get("finish_reason"),
                "usage": usage,
            }
