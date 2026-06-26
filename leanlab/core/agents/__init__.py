"""Agent ports & adapters — the backend-agnostic agent layer the loop depends on."""

from .claude import ClaudeAgent
from .port import AgentResult, AgentRunner, AgentTransport
from .protocol import StructuredRunner, extract_json

__all__ = [
    "AgentResult", "AgentRunner", "AgentTransport",
    "StructuredRunner", "extract_json", "ClaudeAgent",
]
