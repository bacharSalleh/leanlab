"""StructuredRunner — turns any AgentTransport into an AgentRunner.

It enforces the structured-output contract: parse the agent's reply as JSON,
check the required keys, and on malformed output re-prompt the SAME session
("reply with ONLY that JSON object") up to a retry limit. This is the one place
the "agent must return valid structured output" rule lives.
"""

from __future__ import annotations

import json

from .port import AgentResult, AgentRunner, AgentTransport


def _balanced_objects(text):
    """Yield every top-level {...} span in text, brace-balanced and string-aware.

    Unlike a flat `{[^{}]*}` regex, this matches NESTED objects (e.g. a spec reply
    with a `tests` array of objects) even when the agent wraps them in prose or fences.
    """
    depth = start = 0
    in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start:i + 1]


def extract_json(text: str, required_keys) -> dict | None:
    """Return a JSON object in `text` containing all `required_keys`, or None.

    Tries the whole text first, then the last embedded {...} block — agents
    sometimes wrap the object in prose or code fences.
    """
    if not text:
        return None
    text = text.strip()
    candidates = []
    try:
        candidates.append(json.loads(text))
    except json.JSONDecodeError:
        pass
    for span in _balanced_objects(text):
        try:
            candidates.append(json.loads(span))
        except json.JSONDecodeError:
            continue
    for obj in reversed(candidates):
        if isinstance(obj, dict) and all(k in obj for k in required_keys):
            return obj
    return None


class StructuredRunner(AgentRunner):
    """Wraps a transport: validate the JSON reply, re-prompt on malformed output."""

    def __init__(self, transport: AgentTransport, max_retries: int = 2):
        self._transport = transport
        self._max_retries = max_retries

    def run_structured(self, prompt, required_keys, *, session=None) -> AgentResult:
        attempt_prompt, session_id, last_text = prompt, session, ""
        for _attempt in range(self._max_retries + 1):
            session_id, last_text = self._transport.send(attempt_prompt, session=session_id)
            data = extract_json(last_text, required_keys)
            if data is not None:
                return AgentResult(data=data, session_id=session_id, raw=last_text)
            # Malformed — correct and retry in the SAME session.
            attempt_prompt = (
                "Your last reply was NOT a valid JSON object with keys "
                f"{list(required_keys)}. Reply with ONLY that JSON object — no prose, no code fence."
            )
        return AgentResult(data={}, session_id=session_id, raw=last_text)

    def run_plain(self, prompt) -> None:
        self._transport.send(prompt)
