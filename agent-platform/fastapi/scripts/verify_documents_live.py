"""Smoke test destructivo-controlado de la API documental productiva.

Requiere una cuenta con rol de gestión documental. Crea documentos QA, prueba
carga individual/múltiple/carpeta/ZIP, reemplazo, reindexación, descarga,
búsqueda, borrado/restauración y finalmente deja los documentos en soft-delete.
No cambia configuración RAG ni envía mensajes de WhatsApp.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import secrets
import time
import uuid
import zipfile

import httpx
from sqlalchemy import select

from app.core.auth import hash_password
from app.core.database import AsyncSessionLocal, engine
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser


TEMPORARY_EMAIL = "qa-documents@panelagente.saltacloud.com"
LEGACY_TEMPORARY_EMAIL = "qa-documents@local.invalid"


def require(response: httpx.Response, expected: int | tuple[int, ...] = 200):
    expected_values = (expected,) if isinstance(expected, int) else expected
    if response.status_code not in expected_values:
        detail = response.text[:500]
        raise RuntimeError(f"{response.request.method} {response.request.url.path}: {response.status_code} {detail}")
    if response.status_code == 204:
        return None
    if "application/json" in response.headers.get("content-type", ""):
        return response.json()
    return response.content


def wait_for_version(client: httpx.Client, document_id: str, minimum_version: int, timeout: int = 240):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = require(client.get(f"/documents/{document_id}"))
        current = last.get("current_version")
        if current and current["version_number"] >= minimum_version and current["status"] == "ready":
            return last
        job = last.get("current_job") or {}
        if job.get("status") == "failed":
            raise RuntimeError(f"La ingesta falló: {job.get('error_code')} {job.get('error_message')}")
        time.sleep(2)
    raise RuntimeError(f"Timeout esperando versión {minimum_version}; último estado={last}")


def upload(
    client: httpx.Client,
    *,
    area_id: str,
    files: list[tuple[str, bytes, str, str]],
):
    multipart = [("files", (name, content, mime)) for name, content, mime, _ in files]
    data = {
        "area_id": area_id,
        "relative_paths": [relative for _, _, _, relative in files],
    }
    return require(client.post("/documents/upload", data=data, files=multipart), 202)


async def provision_temporary_document_manager() -> tuple[str, str, uuid.UUID]:
    """Crea o reactiva una cuenta QA sin revelar su contraseña efímera."""
    password = secrets.token_urlsafe(32)
    async with AsyncSessionLocal() as db:
        role = (await db.execute(select(AdminRole).where(
            AdminRole.key == "document_manager",
            AdminRole.is_active == True,  # noqa: E712
        ))).scalar_one_or_none()
        if role is None:
            raise RuntimeError("El rol persistente document_manager no está disponible")
        users = (await db.execute(
            select(AdminUser).where(AdminUser.email.in_({
                TEMPORARY_EMAIL,
                LEGACY_TEMPORARY_EMAIL,
            }))
        )).scalars().all()
        user = next((item for item in users if item.email == TEMPORARY_EMAIL), None)
        legacy_user = next((item for item in users if item.email == LEGACY_TEMPORARY_EMAIL), None)
        if user is None:
            user = legacy_user
        elif legacy_user is not None:
            legacy_user.is_active = False
        if user is None:
            user = AdminUser(
                email=TEMPORARY_EMAIL,
                name="QA Documentos",
                hashed_password=hash_password(password),
                role=role.key,
                is_active=True,
                must_change_password=False,
            )
            db.add(user)
        else:
            user.email = TEMPORARY_EMAIL
            user.name = "QA Documentos"
            user.hashed_password = hash_password(password)
            user.role = role.key
            user.is_active = True
            user.must_change_password = False
        await db.commit()
        return user.email, password, user.id


async def deactivate_temporary_document_manager(user_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(AdminUser, user_id)
        if user is not None:
            user.is_active = False
            await db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Confirma que se crearán registros QA en el entorno indicado")
    parser.add_argument(
        "--base-url",
        default=os.getenv("PANEL_E2E_BASE_URL", "https://panelagente.saltacloud.com/api/admin"),
    )
    parser.add_argument(
        "--temporary-user",
        action="store_true",
        help="Crea/reactiva una cuenta document_manager QA y la desactiva al terminar",
    )
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("Use --apply para confirmar el smoke test productivo")
    run_id = uuid.uuid4().hex[:10]
    temporary_user_id: uuid.UUID | None = None
    temporary_loop: asyncio.AbstractEventLoop | None = None
    if args.temporary_user:
        temporary_loop = asyncio.new_event_loop()
        email, password, temporary_user_id = temporary_loop.run_until_complete(
            provision_temporary_document_manager()
        )
    else:
        email = os.getenv("PANEL_E2E_EMAIL")
        password = os.getenv("PANEL_E2E_PASSWORD")
        if not email or not password:
            raise SystemExit("Faltan PANEL_E2E_EMAIL y PANEL_E2E_PASSWORD")

    created_ids: list[str] = []
    try:
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=180, follow_redirects=True) as client:
            tokens = require(client.post("/auth/login", json={"email": email, "password": password}))
            client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
            me = require(client.get("/auth/me"))
            expected_permissions = {"documents.read", "documents.manage"}
            if not expected_permissions.issubset(set(me.get("permissions") or [])):
                raise RuntimeError("La cuenta de prueba no tiene los permisos documentales requeridos")

            # El rol debe quedar aislado del resto del panel y de la configuración RAG.
            require(client.get("/tools/"), 403)
            require(client.patch("/documents/settings", json={"retention_days": 30}), 403)
            require(client.post("/documents/areas", json={"name": f"QA {run_id}", "slug": f"qa-{run_id}"}), 403)

            areas = require(client.get("/documents/areas"))
            active = [area for area in areas if area["is_active"]]
            if not active:
                raise RuntimeError("No hay áreas activas para ejecutar la prueba")
            area_id = next((area["id"] for area in active if area["is_general"]), active[0]["id"])

            individual = upload(client, area_id=area_id, files=[(
                f"qa-individual-{run_id}.txt",
                f"Prueba individual {run_id}. Procedimiento documental verificable.".encode(),
                "text/plain",
                "",
            )])
            if individual["rejected"] or len(individual["accepted"]) != 1:
                raise RuntimeError(f"Carga individual inesperada: {individual}")
            first = individual["accepted"][0]
            created_ids.append(first["document_id"])
            wait_for_version(client, first["document_id"], 1)

            multiple = upload(client, area_id=area_id, files=[
                (f"qa-multiple-a-{run_id}.md", f"# QA A\nContenido múltiple A {run_id}.".encode(), "text/markdown", f"QA-{run_id}/Subcarpeta-A"),
                (f"qa-multiple-b-{run_id}.txt", f"Contenido múltiple B {run_id}.".encode(), "text/plain", f"QA-{run_id}/Subcarpeta-B"),
            ])
            if multiple["rejected"] or len(multiple["accepted"]) != 2:
                raise RuntimeError(f"Carga múltiple/carpeta inesperada: {multiple}")
            for item in multiple["accepted"]:
                created_ids.append(item["document_id"])
                wait_for_version(client, item["document_id"], 1)

            archive_bytes = io.BytesIO()
            with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(f"QA-{run_id}/zip-a.txt", f"Contenido ZIP A {run_id} suficientemente descriptivo.")
                archive.writestr(f"QA-{run_id}/zip-b.md", f"# ZIP B\nContenido ZIP B {run_id} suficientemente descriptivo.")
            zipped = upload(client, area_id=area_id, files=[(
                f"qa-{run_id}.zip", archive_bytes.getvalue(), "application/zip", "",
            )])
            if zipped["rejected"] or len(zipped["accepted"]) != 2:
                raise RuntimeError(f"Carga ZIP inesperada: {zipped}")
            for item in zipped["accepted"]:
                created_ids.append(item["document_id"])
                wait_for_version(client, item["document_id"], 1)

            updated = require(client.patch(
                f"/documents/{first['document_id']}",
                json={"title": f"QA funcional {run_id}", "description": "Documento temporal de validación"},
            ))
            if updated["title"] != f"QA funcional {run_id}":
                raise RuntimeError("La actualización de metadatos no se reflejó")

            replacement_content = f"Reemplazo QA {run_id} con contenido diferente y recuperable.".encode()
            replacement = require(client.post(
                f"/documents/{first['document_id']}/replace",
                files={"file": (f"qa-reemplazo-{run_id}.txt", replacement_content, "text/plain")},
            ), 202)
            if len(replacement["accepted"]) != 1:
                raise RuntimeError(f"Reemplazo inesperado: {replacement}")
            wait_for_version(client, first["document_id"], 2)

            duplicate_replacement = require(client.post(
                f"/documents/{first['document_id']}/replace",
                files={"file": (f"qa-reemplazo-duplicado-{run_id}.txt", replacement_content, "text/plain")},
            ), 202)
            if not duplicate_replacement["accepted"][0]["duplicate_hash"]:
                raise RuntimeError("El reemplazo duplicado no fue identificado por hash")
            wait_for_version(client, first["document_id"], 3)

            versions_before = require(client.get(f"/documents/{first['document_id']}/versions"))
            reindex = require(client.post(f"/documents/{first['document_id']}/reindex"), 202)
            if reindex["status"] != "queued":
                raise RuntimeError(f"Reindexación no encolada: {reindex}")
            wait_for_version(client, first["document_id"], versions_before[0]["version_number"] + 1)

            download = client.get(f"/documents/{first['document_id']}/download")
            require(download)
            if not download.content:
                raise RuntimeError("La descarga devolvió un archivo vacío")

            hits = require(client.post("/documents/search", json={
                "query": f"Reemplazo QA {run_id} contenido diferente recuperable",
                "area_ids": [area_id],
            }))
            if not isinstance(hits, list) or not any(
                hit.get("reference_code") == first["reference_code"] for hit in hits
            ):
                raise RuntimeError("La búsqueda no recuperó el documento reemplazado")

            require(client.delete(f"/documents/{first['document_id']}"), 204)
            restored = require(client.post(f"/documents/{first['document_id']}/restore"))
            if restored["status"] != "published":
                raise RuntimeError("La restauración no republicó el documento")

            print(
                f"OK run_id={run_id} uploads=individual,multiple,folder,zip "
                f"replace=ok duplicate_replace=ok reindex=ok download=ok "
                f"search_hits={len(hits)} delete_restore=ok "
                f"role_isolation=ok"
            )
    finally:
        # Los registros quedan en soft-delete y se purgan según la retención normal.
        if created_ids:
            try:
                with httpx.Client(
                    base_url=args.base_url.rstrip("/"), timeout=180, follow_redirects=True
                ) as cleanup_client:
                    tokens = require(cleanup_client.post(
                        "/auth/login", json={"email": email, "password": password}
                    ))
                    cleanup_client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
                    for document_id in created_ids:
                        response = cleanup_client.delete(f"/documents/{document_id}")
                        if response.status_code not in {204, 404}:
                            print(f"WARN cleanup document_id={document_id} status={response.status_code}")
            except Exception as exc:  # La falla original conserva prioridad sobre la limpieza.
                print(f"WARN cleanup_failed type={type(exc).__name__}")
        if temporary_user_id is not None:
            assert temporary_loop is not None
            temporary_loop.run_until_complete(
                deactivate_temporary_document_manager(temporary_user_id)
            )
        if temporary_loop is not None:
            temporary_loop.run_until_complete(engine.dispose())
            temporary_loop.close()


if __name__ == "__main__":
    main()
