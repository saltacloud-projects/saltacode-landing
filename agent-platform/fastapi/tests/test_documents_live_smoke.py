"""Contratos locales del verificador productivo de Documentos."""

import httpx

from scripts.verify_documents_live import require, upload


def test_require_returns_binary_download_without_json_decoding():
    response = httpx.Response(
        200,
        content=b"document-content",
        headers={"content-type": "application/pdf"},
        request=httpx.Request("GET", "https://panel.example/document.pdf"),
    )

    assert require(response) == b"document-content"


def test_upload_encodes_repeated_relative_paths_as_multipart_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert body.count(b'name="files"') == 2
        assert body.count(b'name="relative_paths"') == 2
        assert b'name="area_id"' in body
        return httpx.Response(202, json={"accepted": [{}, {}], "rejected": []})

    with httpx.Client(
        base_url="https://panel.example/api/admin",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = upload(
            client,
            area_id="area-1",
            files=[
                ("a.txt", b"A", "text/plain", "Area/A"),
                ("b.txt", b"B", "text/plain", "Area/B"),
            ],
        )

    assert len(result["accepted"]) == 2
