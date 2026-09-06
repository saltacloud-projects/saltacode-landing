"""Restricted HTTP executor shared by source tests and declarative tools."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.models.integration_source import IntegrationSource
from app.services.credentials import (
    CredentialDecryptError,
    CredentialStoreUnavailable,
    credential_cipher,
)

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie"}


class SourceRequestError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class HttpExecutionResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
    duration_ms: int


async def _resolved_addresses(
    hostname: str, port: int
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise SourceRequestError(
            "source_dns_error", "integration source hostname cannot be resolved"
        ) from exc
    addresses = set()
    for info in infos:
        try:
            addresses.add(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not addresses:
        raise SourceRequestError(
            "source_dns_error", "integration source resolved to no usable address"
        )
    return addresses


async def validate_source_destination(source: IntegrationSource, path: str) -> str:
    if not path.startswith("/") or "://" in path:
        raise SourceRequestError(
            "invalid_source_path", "operation path must be relative"
        )
    base = urlsplit(source.base_url)
    if base.scheme not in {"https", "http"} or not base.hostname:
        raise SourceRequestError(
            "invalid_source_url", "integration source URL is invalid"
        )
    host = base.hostname.lower().rstrip(".")
    allowed_hosts = {
        str(item).lower().rstrip(".") for item in (source.allowed_hosts or [])
    }
    if host not in allowed_hosts:
        raise SourceRequestError(
            "source_host_denied", "integration source host is not allowlisted"
        )
    if base.scheme != "https" and not source.allow_private_network:
        raise SourceRequestError(
            "source_tls_required", "public integration sources require HTTPS"
        )

    port = base.port or (443 if base.scheme == "https" else 80)
    addresses = await _resolved_addresses(host, port)
    if not source.allow_private_network and any(
        not address.is_global for address in addresses
    ):
        raise SourceRequestError(
            "source_network_denied",
            "integration source resolved to a private or reserved address",
        )
    return urljoin(source.base_url.rstrip("/") + "/", path.lstrip("/"))


def _request_auth(
    source: IntegrationSource,
    credentials: dict[str, str],
    headers: dict[str, str],
    query: dict[str, Any],
) -> httpx.Auth | None:
    auth_type = source.auth_type
    config = source.auth_config or {}
    if auth_type == "none":
        return None
    if auth_type in {"bearer", "token"}:
        token = credentials.get("token")
        if not token:
            raise SourceRequestError(
                "source_credentials_missing", "integration source token is missing"
            )
        scheme = "Bearer" if auth_type == "bearer" else "Token"
        headers["Authorization"] = f"{scheme} {token}"
        return None
    if auth_type == "api_key":
        value = credentials.get("value")
        name = str(config.get("name") or "X-API-Key")
        location = str(config.get("in") or "header")
        if not value:
            raise SourceRequestError(
                "source_credentials_missing", "integration source API key is missing"
            )
        if location == "query":
            query[name] = value
        elif name.lower() not in _SECRET_HEADERS:
            headers[name] = value
        else:
            raise SourceRequestError(
                "source_auth_config_invalid", "API key header is not allowed"
            )
        return None
    if auth_type == "basic":
        username = credentials.get("username")
        password = credentials.get("password")
        if not username or password is None:
            raise SourceRequestError(
                "source_credentials_missing", "basic credentials are incomplete"
            )
        return httpx.BasicAuth(username, password)
    raise SourceRequestError(
        "source_auth_unsupported", "integration source authentication is unsupported"
    )


class RestrictedHttpExecutor:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._clients: dict[bool, httpx.AsyncClient] = {}

    def _client(self, verify_tls: bool) -> httpx.AsyncClient:
        client = self._clients.get(verify_tls)
        if client is None:
            client = httpx.AsyncClient(
                verify=verify_tls,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )
            self._clients[verify_tls] = client
        return client

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def execute(
        self,
        source: IntegrationSource,
        *,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> HttpExecutionResponse:
        method = method.upper()
        if method not in ALLOWED_METHODS:
            raise SourceRequestError("method_not_allowed", "HTTP method is not enabled")
        if not source.is_active:
            raise SourceRequestError(
                "source_disabled", "integration source is disabled"
            )

        url = await validate_source_destination(source, path)
        request_headers = {
            str(key): str(value)
            for key, value in (source.default_headers or {}).items()
        }
        for key, value in (headers or {}).items():
            if key.lower() in _SECRET_HEADERS:
                raise SourceRequestError(
                    "header_denied", "operation cannot override secret-bearing headers"
                )
            request_headers[str(key)] = str(value)
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key
        request_query = dict(query or {})
        try:
            credentials = credential_cipher.decrypt(source.encrypted_credentials)
        except CredentialStoreUnavailable as exc:
            raise SourceRequestError(
                "credential_store_unavailable",
                "integration credential store is unavailable",
            ) from exc
        except CredentialDecryptError as exc:
            raise SourceRequestError(
                "source_credentials_invalid",
                "integration credentials cannot be decrypted",
            ) from exc
        auth = _request_auth(source, credentials, request_headers, request_query)

        started = time.monotonic()
        timeout = httpx.Timeout(float(source.timeout_seconds))
        try:
            client = self._client(source.verify_tls)
            async with client.stream(
                method,
                url,
                params=request_query or None,
                json=json_body,
                headers=request_headers,
                auth=auth,
                timeout=timeout,
            ) as response:
                content_length = response.headers.get("content-length", "")
                if (
                    content_length.isdigit()
                    and int(content_length) > source.max_response_bytes
                ):
                    raise SourceRequestError(
                        "source_response_too_large",
                        "integration response exceeds its size limit",
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > source.max_response_bytes:
                        raise SourceRequestError(
                            "source_response_too_large",
                            "integration response exceeds its size limit",
                        )
                    chunks.append(chunk)
                content = b"".join(chunks)
                status_code = response.status_code
                response_headers = {
                    "content-type": response.headers.get("content-type", ""),
                }
        except SourceRequestError:
            raise
        except httpx.TimeoutException as exc:
            raise SourceRequestError(
                "source_timeout", "integration source timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceRequestError(
                "source_connection_error", "integration source request failed"
            ) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        return HttpExecutionResponse(
            status_code=status_code,
            headers=response_headers,
            content=content,
            duration_ms=duration_ms,
        )


restricted_http_executor = RestrictedHttpExecutor()
