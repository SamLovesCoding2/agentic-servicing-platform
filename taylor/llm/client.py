"""
OpenAI client wrapper for the Taylor agent.

Uses the OpenAI Responses API (or Chat Completions as fallback).
Handles tool calling, system prompts, and response parsing.

The LLM is the nondeterministic reasoning engine. It proposes actions.
Code (the tool registry, state machine, completion gate) authorizes
and executes them.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper around the OpenAI async client."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def chat_with_tools(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """
        Call the LLM with optional tool definitions.

        Returns:
            {
                "content": str | None,       # text response
                "tool_calls": list | None,    # tool call requests
                "finish_reason": str,         # stop, tool_calls, length
                "usage": dict,                # token usage
            }
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": user_message})

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message

            tool_calls = None
            if message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })

            return {
                "content": message.content,
                "tool_calls": tool_calls,
                "finish_reason": choice.finish_reason,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                } if response.usage else None,
            }
        except Exception as e:
            logger.error(f"LLM call failed: {type(e).__name__}")
            # NEVER expose raw API errors to the customer.
            # Return a clean, safe message. The error details go in the "error" field
            # for logging and debugging, not in "content" which reaches the customer.
            error_type = type(e).__name__
            if "insufficient_quota" in str(e) or "credit_balance" in str(e):
                friendly = "I'm having trouble connecting right now. Let me transfer you to an agent who can help."
            elif "rate_limit" in str(e).lower() or "429" in str(e):
                friendly = "I'm experiencing high demand right now. Let me transfer you to an agent."
            elif "timeout" in str(e).lower() or "timed out" in str(e).lower():
                friendly = "I'm taking longer than expected. Let me transfer you to an agent."
            elif "auth" in str(e).lower() or "401" in str(e) or "key" in str(e).lower():
                friendly = "I'm having trouble connecting right now. Let me transfer you to an agent."
            else:
                friendly = "I'm having trouble right now. Let me transfer you to an agent who can help."

            return {
                "content": friendly,
                "tool_calls": None,
                "finish_reason": "error",
                "usage": None,
                "error": f"{error_type}: {str(e)[:200]}",
            }

    async def classify_intent(
        self,
        utterance: str,
        available_routes: list[str],
        system_prompt: str | None = None,
    ) -> str:
        """
        Use the LLM to classify intent into one of the available routes.
        Falls back to 'knowledge' if classification fails.

        This is the LLM-assisted part of the router. The router validates
        the LLM's choice against channel + auth constraints.
        """
        if not system_prompt:
            system_prompt = (
                "You are an intent classifier for a customer service system. "
                "Classify the user's message into exactly one of these categories: "
                f"{', '.join(available_routes)}. "
                "Respond with only the category name, nothing else."
            )

        try:
            response = await self.client.chat.completions.create(
                model=os.environ.get("OPENAI_ROUTER_MODEL", self._model),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": utterance},
                ],
                temperature=0.0,
                max_tokens=50,
            )
            result = response.choices[0].message.content.strip().lower()
            if result in available_routes:
                return result
            return "knowledge"  # safe default
        except Exception as e:
            logger.warning(f"LLM classification failed, falling back: {e}")
            return "knowledge"
