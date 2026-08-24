"""Prompt composition primitives without provider or business coupling."""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSection:
    key: str
    content: str
    precedence: int

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("prompt section key must not be empty")
        if not self.content.strip():
            raise ValueError("prompt section content must not be empty")


def compose_prompt_sections(sections: Iterable[PromptSection]) -> str:
    """Compose unique sections in explicit precedence order."""

    ordered = sorted(sections, key=lambda section: section.precedence)
    keys = [section.key for section in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("prompt section keys must be unique")
    return "\n\n".join(section.content.strip() for section in ordered)
