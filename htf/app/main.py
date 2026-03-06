"""
Main entry point for running the Supply Chain Resilience Agent.

Usage:
  python main.py                    # Interactive mode
  python main.py --init             # Initialize/seed database only
  python main.py --query "..."      # Run a single query
"""

import asyncio
import os
import sys
import argparse

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.db_init import init_database, seed_data


def _patch_rate_limit_retry():
    """Monkeypatch google.genai to auto-retry on 429 (free tier rate limit)."""
    from google.genai import models as _genai_models
    from google.genai.errors import ClientError

    _original = _genai_models.AsyncModels._generate_content

    async def _with_retry(self, **kwargs):
        for attempt in range(8):
            try:
                return await _original(self, **kwargs)
            except ClientError as e:
                if "429" in str(e) and attempt < 7:
                    wait = 15 + attempt * 5
                    print(f"  [Rate limited, retry in {wait}s ({attempt+1}/7)]")
                    await asyncio.sleep(wait)
                else:
                    raise

    _genai_models.AsyncModels._generate_content = _with_retry


async def run_agent(user_query: str) -> str:
    """Run a single query through the agent pipeline."""
    _patch_rate_limit_retry()
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from supply_chain_agent.agent import root_agent

    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="supply_chain_resilience",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="supply_chain_resilience",
        user_id="demo_user",
    )

    from google.genai import types

    content = types.Content(
        role="user",
        parts=[types.Part(text=user_query)],
    )

    final_response = ""
    async for event in runner.run_async(
        user_id="demo_user",
        session_id=session.id,
        new_message=content,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_response += part.text

    return final_response


async def interactive_mode():
    """Run in interactive mode with a REPL."""
    print("=" * 70)
    print("  Supply Chain Resilience Agent - Interactive Mode")
    print("  Type 'quit' to exit, 'help' for example queries")
    print("=" * 70)

    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not query:
            continue
        if query.lower() == "quit":
            break
        if query.lower() == "help":
            print("""
Example queries:
  - Run a full disruption analysis
  - What happens if our Taiwan suppliers are disrupted?
  - Check for current supply chain risks
  - What did we do last time there was an earthquake in Taiwan?
  - Analyze the risk if RareEarth Mining Co fails
  - Show me our supply chain bottlenecks
""")
            continue

        print("\nProcessing...\n")
        try:
            response = await run_agent(query)
            print(response)
        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Supply Chain Resilience Agent")
    parser.add_argument("--init", action="store_true", help="Initialize and seed database")
    parser.add_argument("--query", type=str, help="Run a single query")
    args = parser.parse_args()

    # Always init database
    engine = init_database()
    seed_data(engine)

    if args.init:
        print("Database initialized successfully.")
        return

    if args.query:
        response = asyncio.run(run_agent(args.query))
        print(response)
    else:
        asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
