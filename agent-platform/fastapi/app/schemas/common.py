"""Shared channel and execution enums."""

from enum import Enum


class ChannelEnum(str, Enum):
    whatsapp = "whatsapp"
    api = "api"
    web = "web"


class InputTypeEnum(str, Enum):
    text = "text"
    file = "file"
    image = "image"
    audio = "audio"


class SourceSystemEnum(str, Enum):
    documents = "documents"
    files = "files"
    integration = "integration"
    internal = "internal"
    unsupported = "unsupported"
    images = "images"


class StatusEnum(str, Enum):
    success = "success"
    error = "error"
    blocked = "blocked"
    quota_exceeded = "quota_exceeded"
    unsupported = "unsupported"
