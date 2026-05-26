import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT),
)

from clients.brain_client import (
    build_brain_system_prompt,
)
from contracts.context_contract import (
    DEEP_THOUGHT_ACTION,
)
from settings.app_settings import settings
from settings.config_loader import (
    config,
)
from utils.response_extractor import (
    ResponseExtractor,
)
from utils.runtime_actions import (
    extract_runtime_actions,
)
from utils.urls import (
    join_url,
)


DEFAULT_CASES = [
    (
        "simple_location",
        "Where do you think you are right now?",
    ),
    (
        "light_opinion",
        "What is a good name for a tiny local AI runtime?",
    ),
    (
        "reflection",
        "Think carefully about your internal state and answer: what are you?",
    ),
    (
        "multi_step",
        "Compare these two designs and choose one: runtime markers or plain text instructions. Be concise.",
    ),
]


@dataclass
class ProbeContext:
    deep_thought_count: int = 0


def runtime_target():

    if settings.USE_SERVICE_AS_BRAIN:
        return (
            settings.SERVICE_API_BASE,
            settings.SERVICE_MODEL_UID,
            config.SERVICE_TEMPERATURE,
            config.SERVICE_MAX_TOKENS,
        )

    return (
        settings.BRAIN_API_BASE,
        settings.BRAIN_MODEL_UID,
        config.BRAIN_TEMPERATURE,
        config.BRAIN_MAX_TOKENS,
    )


async def run_case(
    client: httpx.AsyncClient,
    *,
    name: str,
    prompt: str,
    counter: int,
) -> dict:

    api_base, model, temperature, max_tokens = runtime_target()

    context = ProbeContext(
        deep_thought_count=counter
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": build_brain_system_prompt(
                    context
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    response = await client.post(
        join_url(
            api_base,
            settings.CHAT_ENDPOINT,
        ),
        json=payload,
        timeout=120,
    )

    response.raise_for_status()
    result = response.json()

    reasoning = (
        ResponseExtractor
        .extract_reasoning_text(
            result
        )
    )

    content = (
        ResponseExtractor
        .extract_content_text(
            result
        )
    )

    reasoning_actions = extract_runtime_actions(
        reasoning
    )

    content_actions = extract_runtime_actions(
        content
    )

    action_count = (
        reasoning_actions.deep_thought_count
        + content_actions.deep_thought_count
    )

    return {
        "case": name,
        "counter": counter,
        "called": action_count > 0,
        "raw_marker_count": action_count,
        "runtime_call_count": min(
            action_count,
            1,
        ),
        "marker": DEEP_THOUGHT_ACTION,
        "content_preview": content_actions.text[:240],
        "reasoning_preview": reasoning_actions.text[:240],
    }


async def main():

    if hasattr(
        sys.stdout,
        "reconfigure",
    ):
        sys.stdout.reconfigure(
            encoding="utf-8"
        )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--counter",
        type=int,
        action="append",
        default=None,
    )
    parser.add_argument(
        "--prompt",
        action="append",
        default=None,
    )
    args = parser.parse_args()

    counters = args.counter or [
        0,
        1,
        3,
    ]

    cases = DEFAULT_CASES

    if args.prompt:
        cases = [
            (
                f"custom_{index + 1}",
                prompt,
            )
            for index, prompt
            in enumerate(args.prompt)
        ]

    async with httpx.AsyncClient() as client:

        for counter in counters:

            for name, prompt in cases:

                result = await run_case(
                    client,
                    name=name,
                    prompt=prompt,
                    counter=counter,
                )

                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                    )
                )


if __name__ == "__main__":
    asyncio.run(
        main()
    )
