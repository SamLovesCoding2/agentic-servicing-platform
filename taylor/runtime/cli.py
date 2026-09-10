#!/usr/bin/env python
"""
Interactive CLI for the Salient Replica.

Lets you have real conversations with the Taylor agent through the
full safety system (router, tool registry, state machine, completion gate).

Usage:
    python -m taylor.runtime.cli
    python -m taylor.runtime.cli --auth step_up --channel sms --account ACC-001
    python -m taylor.runtime.cli --no-llm  # deterministic mode for testing

Commands within the CLI:
    /auth <level>     — set auth level (anonymous, verified, step_up)
    /channel <ch>     — set channel (sms, chat, voice)
    /account <id>     — set account ID
    /tools            — show visible tools for current state
    /history          — show conversation history
    /reset            — clear conversation history
    /quit             — exit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from taylor.graphs.universal.state import AuthLevel, Channel
from taylor.runtime.text_runtime import TextRuntime

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Salient Replica interactive CLI")
    parser.add_argument("--auth", default="verified", choices=["anonymous", "verified", "step_up"],
                        help="Initial auth level")
    parser.add_argument("--channel", default="sms", choices=["sms", "chat", "voice"],
                        help="Channel to use")
    parser.add_argument("--account", default="ACC-001", help="Account ID")
    parser.add_argument("--customer", default="cust-001", help="Customer ID")
    parser.add_argument("--conversation", default="cli-session-001", help="Conversation ID")
    parser.add_argument("--no-llm", action="store_true", help="Run in deterministic mode (no LLM)")
    parser.add_argument("--debug", action="store_true", help="Show debug info")
    return parser.parse_args()


async def main():
    args = parse_args()

    if args.debug:
        logging.getLogger("taylor").setLevel(logging.DEBUG)

    # Create runtime
    llm_client = None
    if not args.no_llm:
        import os
        if os.environ.get("OPENAI_API_KEY"):
            from taylor.llm.client import LLMClient
            llm_client = LLMClient()
        else:
            print("⚠ No OPENAI_API_KEY set. Running in deterministic mode.")
            print("  Set OPENAI_API_KEY in .env or environment to enable LLM-powered responses.\n")

    # Try to connect to database (optional)
    database = None
    try:
        from marshall.core.database import Database
        db = Database()
        await db.create_tables()
        database = db
        if args.debug:
            print("✓ Database connected")
    except Exception as e:
        if args.debug:
            print(f"– Database not available: {e}")

    runtime = TextRuntime(llm_client=llm_client, database=database)

    # Session state
    auth_level = AuthLevel(args.auth)
    channel = Channel(args.channel)
    account_id = args.account
    customer_id = args.customer
    conversation_id = args.conversation

    # Header
    mode = "LLM-powered" if runtime.has_llm else "deterministic"
    print("=" * 60)
    print("  Salient Replica — Taylor Agent")
    print(f"  Mode: {mode}")
    print(f"  Channel: {channel.value} | Auth: {auth_level.value} | Account: {account_id}")
    print("=" * 60)
    print()
    if runtime.has_llm:
        print("You're talking to Taylor, a customer service agent for")
        print("Fictional Auto Credit (FAC). Type naturally.")
    else:
        print("Running in deterministic mode (no LLM). Responses are")
        print("predefined. Set OPENAI_API_KEY for real AI responses.")
    print()
    print("Commands: /auth, /channel, /account, /tools, /history, /reset, /quit")
    print()

    # Show initial greeting
    if runtime.has_llm:
        print("Taylor: Hello! I'm here to help with your FAC account. How can I assist you today?")
        runtime._history[conversation_id] = [
            {"role": "assistant", "content": "Hello! I'm here to help with your FAC account. How can I assist you today?"}
        ]
    else:
        print("Taylor: [greeting]")

    # Main loop
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "/quit":
                print("Goodbye!")
                break
            elif cmd == "/auth":
                try:
                    auth_level = AuthLevel(arg)
                    print(f"  → Auth level set to: {auth_level.value}")
                except ValueError:
                    print(f"  → Invalid auth level. Use: anonymous, verified, step_up")
            elif cmd == "/channel":
                try:
                    channel = Channel(arg)
                    print(f"  → Channel set to: {channel.value}")
                except ValueError:
                    print(f"  → Invalid channel. Use: sms, chat, voice")
            elif cmd == "/account":
                account_id = arg
                print(f"  → Account set to: {account_id}")
            elif cmd == "/tools":
                state = {
                    "auth_level": auth_level,
                    "action_status": "PROPOSED",
                }
                tools = runtime.get_visible_tools(state, channel.value)
                print(f"  → Visible tools for {channel.value}/{auth_level.value}:")
                for t in tools:
                    print(f"    - {t}")
            elif cmd == "/history":
                history = runtime._history.get(conversation_id, [])
                print(f"  → Conversation history ({len(history)} messages):")
                for msg in history:
                    print(f"    [{msg['role']}] {msg['content'][:100]}")
            elif cmd == "/reset":
                runtime.clear_history(conversation_id)
                print("  → Conversation history cleared")
            else:
                print(f"  → Unknown command: {cmd}")
            continue

        # Run the turn
        try:
            result = await runtime.run_turn(
                utterance=user_input,
                conversation_id=conversation_id,
                customer_id=customer_id,
                auth_level=auth_level,
                channel=channel,
                account_id=account_id,
            )

            # Show the reply
            print(f"\nTaylor: {result['reply']}")

            # Show debug info if requested
            if args.debug:
                print(f"  [route={result['route']} exit={result['exit_state']} "
                      f"action={result.get('action_status')} "
                      f"success_allowed={result.get('success_language_allowed')}]")
                if result.get("tool_calls_made"):
                    for tc in result["tool_calls_made"]:
                        print(f"  [tool: {tc['tool']} → {tc['status']}]")
                if result.get("usage"):
                    u = result["usage"]
                    print(f"  [tokens: {u.get('total_tokens', '?')}]")

        except Exception as e:
            print(f"\nTaylor: I'm sorry, I encountered an error. {str(e)[:200]}")
            if args.debug:
                import traceback
                traceback.print_exc()

    # Cleanup
    if database:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
