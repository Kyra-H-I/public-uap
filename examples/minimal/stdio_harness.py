# Exported from the reference implementation's test suite.
# The worked example of wrapping a provider for uap-conform over stdio.
"""Expose the reference FakeProvider to the wire-level conformance runner over stdio.

This is the ~20-line harness the runner's docs promise: read one JSON envelope per
line, dispatch on ``type``, reply on stdout echoing ``id``. It exists so the Go
runner can be held to the same verdicts as the in-process Python suite against the
same provider — and it doubles as the worked example of wrapping a provider for
`uap-conform`, which is why it ships in the published bundle.

Run from the directory holding this file and its provider (the runner does this
via ``-cmd``):

    python stdio_harness.py

stdout is the protocol; anything a harness wants to log goes to stderr.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from uap_core.model import (
    MAX_COMMAND_ID_CHARS,
    ActionCall,
    ActionCallDecodeError,
    ActionResult,
    ActionStatus,
    Expectation,
    ObservationQuery,
)
from provider import FakeProvider


async def _reply(provider: FakeProvider, message: dict[str, Any]) -> dict[str, Any]:
    kind = message.get("type")
    if kind == "uap.describe_request":
        return (await provider.describe()).to_dict()
    if kind == "uap.capability_request":
        descriptors = await provider.describe_capability(str(message.get("capability", "")))
        return {"actions": [d.to_dict() for d in descriptors]}
    if kind == "uap.observe_request":
        return (await provider.observe(ObservationQuery.from_dict(message))).to_dict()
    if kind == "uap.invoke_request":
        try:
            call = ActionCall.from_dict(message)
        except ActionCallDecodeError as exc:
            # Decoding actionable input is atomic. Returning a repair-grade refusal
            # keeps the provider process alive and, critically, never invokes with a
            # silently coerced control field or subset of the caller's arguments.
            return _invalid_call(message, exc).to_dict()
        return (await provider.invoke(call)).to_dict()
    if kind == "uap.verify_request":
        return (await provider.verify(Expectation.from_dict(message))).to_dict()
    if kind == "uap.cancel_request":
        return (await provider.cancel(str(message.get("command_id", "")))).to_dict()
    return {"error": {"code": "unsupported", "message": f"unknown request {kind!r}"}}


def _invalid_call(message: dict[str, Any], exc: ActionCallDecodeError) -> ActionResult:
    raw_command_id = message.get("command_id")
    command_id = (
        raw_command_id
        if isinstance(raw_command_id, str) and 0 < len(raw_command_id) <= MAX_COMMAND_ID_CHARS
        else ""
    )
    return ActionResult(
        command_id=command_id,
        status=ActionStatus.REJECTED,
        error=exc.to_uap_error(),
        detail="the action call needs repair",
    )


async def main() -> None:
    provider = FakeProvider()
    for line in sys.stdin:  # sequential by design: one request in flight at a time
        if not line.strip():
            continue
        message = json.loads(line)
        payload = await _reply(provider, message)
        envelope = {
            "type": str(message.get("type", "")).replace("_request", "_result"),
            "id": message.get("id"),
            **payload,
        }
        print(json.dumps(envelope), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
