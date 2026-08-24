import pytest

from saltacode_agent.domain.prompt import PromptSection, compose_prompt_sections


def test_prompt_sections_follow_explicit_precedence() -> None:
    sections = [
        PromptSection(key="domain", content="Domain", precedence=20),
        PromptSection(key="time", content="Time", precedence=0),
        PromptSection(key="policy", content="Policy", precedence=10),
    ]

    assert compose_prompt_sections(sections) == "Time\n\nPolicy\n\nDomain"


def test_prompt_sections_require_unique_keys() -> None:
    with pytest.raises(ValueError, match="unique"):
        compose_prompt_sections(
            [
                PromptSection(key="policy", content="First", precedence=1),
                PromptSection(key="policy", content="Second", precedence=2),
            ]
        )
