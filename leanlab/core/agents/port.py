"""Agent ports — the abstraction the loop depends on (Dependency Inversion).

The loop never talks to a concrete agent backend. It depends on `AgentRunner`.
A backend implements the low-level `AgentTransport` (send one prompt, get text);
`StructuredRunner` (protocol.py) adapts a transport into an `AgentRunner` by
adding JSON validation and retry. Swapping in Hermes or a custom backend means a
new `AgentTransport` — nothing in the loop changes (open/closed).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AgentResult:
    """The outcome of one structured agent turn."""

    data: dict              # validated JSON the agent returned ({} if it never produced valid output)
    session_id: str | None = None   # to resume the same agent session
    raw: str = ""           # the agent's last raw reply, for diagnostics

    @property
    def ok(self) -> bool:
        return bool(self.data)


class AgentTransport(ABC):
    """Low-level: send one prompt to an agent backend, get back (session_id, text)."""

    @abstractmethod
    def send(self, prompt: str, *, session: str | None = None) -> tuple[str | None, str]:
        """Run one turn. Return (session_id, final_text). Raise on transport failure."""
        raise NotImplementedError


class AgentRunner(ABC):
    """High-level: what the loop depends on — structured output and fire-and-forget."""

    @abstractmethod
    def run_structured(self, prompt: str, required_keys, *, session: str | None = None) -> AgentResult:
        """Run a turn and return a JSON object that contains all `required_keys`."""
        raise NotImplementedError

    @abstractmethod
    def run_plain(self, prompt: str) -> None:
        """Run a fire-and-forget turn (e.g. the Director or Critic writing a file)."""
        raise NotImplementedError
