"""Classify persisted message authors without consulting current conversation control."""


def message_author_type(role: str, origin: object, has_execution: bool) -> str:
    if role == "user":
        return "visitor"
    if origin == "operator":
        return "operator"
    return "agent" if has_execution else "unknown"
