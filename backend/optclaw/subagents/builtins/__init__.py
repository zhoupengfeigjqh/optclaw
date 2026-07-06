"""Built-in subagent configurations."""

from .coder_agent import CODER_AGENT_CONFIG
from .general_purpose import GENERAL_PURPOSE_CONFIG

# Registry of built-in subagents
BUILTIN_SUBAGENTS = {
    "general-purpose": GENERAL_PURPOSE_CONFIG,
    "coder": CODER_AGENT_CONFIG,
}

__all__ = [
    "GENERAL_PURPOSE_CONFIG",
    "CODER_AGENT_CONFIG"
]