"""The expert system: decides whether SQL written by Gemini may run. Owner: Afraz."""

from agent.validator.engine import validate

__all__ = ["validate"]
