"""Typed application failures safe to map at transport boundaries."""


class RuntimeUnavailableError(RuntimeError):
    """Raised when execution adapters are not production-ready."""
