"""
Agent Platform — PipelineService
Orquesta el procesamiento de un mensaje de WhatsApp con filosofía de AGENTE:
  1. Governance  — verificar autorización del número (gate de seguridad)
  2. AgentProfile — cargar identidad/personalidad del agente
  3. Memoria     — cargar ventana de conversación
  4. Audio       — transcribir notas de voz (Whisper)
  5. Tools       — cargar herramientas disponibles (incluye DB para superusuarios)
  6. Agent Loop  — cerebro único: conversa, razona y usa herramientas/bases
  7. Response    — enviar respuesta + archivos por WhatsApp
  8. Memoria/Audit — persistir conversación y auditar

No hay clasificador, menús, ni ramas de intent enlatadas: el agente maneja
todo. El único gate que permanece es el de seguridad (auth + permisos).
"""

import logging
import time
import uuid

from sqlalchemy import select

from app.core.concurrency import pipeline_semaphore
from app.core.database import AsyncSessionLocal
from app.core.dedup_lock import conversation_lock
from app.models.tool_config import ToolConfig
from app.schemas.audit import AuditLogCreate
from app.schemas.common import ChannelEnum, InputTypeEnum, StatusEnum
from app.schemas.governance import AccessCheckRequest
from app.services.agent_profile import agent_profile_service
from app.services.agent_runtime import ResolvedAgentRuntime
from app.services.audit import audit_service
from app.services.configuration import configuration_service
from app.services.conversation import conversation_service
from app.services.governance import governance_service
from app.services.tools.registry import tool_registry
from app.services.transcription import transcription_service
from app.services.whatsapp import WhatsAppConnectionContext, whatsapp_service

logger = logging.getLogger(__name__)


class PipelineService:
    async def process_whatsapp_message(
        self,
        phone: str,
        content: str,
        message_id: str,
        input_type: str = "text",
        audio_media_id: str | None = None,
        interactive_id: str | None = None,
        quoted_id: str | None = None,
        redis=None,
        resolved_runtime: ResolvedAgentRuntime | None = None,
        whatsapp_connection: WhatsAppConnectionContext | None = None,
        route_key: str | None = None,
        channel_route_id: uuid.UUID | None = None,
    ) -> None:
        """
        Pipeline completo de procesamiento de un mensaje entrante.
        Ejecuta en background — no bloquea la respuesta HTTP a Meta.

        Para mensajes de audio: descarga y transcribe con Whisper antes
        de continuar el flujo normal como si fuera texto.

        Para selecciones de menú interactivo (`interactive_id` presente):
        enruta determinísticamente según el id antes de involucrar al LLM.
        """
        request_id = str(uuid.uuid4())
        start = time.monotonic()
        if resolved_runtime is not None and (
            whatsapp_connection is None or route_key is None or channel_route_id is None
        ):
            raise ValueError("resolved WhatsApp runtime requires route context")
        if resolved_runtime is None:
            logger.warning("legacy_whatsapp_pipeline_without_resolved_runtime")

        logger.info(
            "pipeline_started",
            extra={
                "request_id": request_id,
                "phone": phone,
                "content_preview": content[:80] if content else "",
                "message_id": message_id,
                "interactive_id": interactive_id,
            },
        )

        # Backpressure global: limita el número de pipelines concurrentes.
        # Si llegan más mensajes que el límite, los siguientes esperan en cola.
        # Como el webhook ya respondió 200 a Meta y este pipeline corre en
        # background, la espera no afecta a Meta ni al usuario.
        async with pipeline_semaphore:
            logger.debug(
                "pipeline_semaphore_acquired",
                extra={"request_id": request_id, "phone": phone},
            )
            # Serialización por usuario: evita que dos mensajes consecutivos del
            # mismo phone corran en paralelo y corrompan memoria/retry/orden.
            await self._process_with_user_lock(
                phone=phone,
                content=content,
                message_id=message_id,
                input_type=input_type,
                audio_media_id=audio_media_id,
                interactive_id=interactive_id,
                quoted_id=quoted_id,
                redis=redis,
                request_id=request_id,
                start=start,
                resolved_runtime=resolved_runtime,
                whatsapp_connection=whatsapp_connection,
                route_key=route_key,
                channel_route_id=channel_route_id,
            )

    async def _process_with_user_lock(
        self,
        *,
        phone: str,
        content: str,
        message_id: str,
        input_type: str,
        audio_media_id: str | None,
        interactive_id: str | None,
        quoted_id: str | None,
        redis,
        request_id: str,
        start: float,
        resolved_runtime: ResolvedAgentRuntime | None,
        whatsapp_connection: WhatsAppConnectionContext | None,
        route_key: str | None,
        channel_route_id: uuid.UUID | None,
    ) -> None:
        """Wrap _process_locked() with the per-user Redis lock."""
        lock_subject = f"{channel_route_id or 'legacy'}:{phone}"
        async with conversation_lock(redis, lock_subject, request_id) as lock_acquired:
            if not lock_acquired:
                logger.info(
                    "pipeline_proceeding_without_lock",
                    extra={"request_id": request_id, "phone": phone},
                )
            await self._process_locked(
                phone=phone,
                content=content,
                message_id=message_id,
                input_type=input_type,
                audio_media_id=audio_media_id,
                interactive_id=interactive_id,
                quoted_id=quoted_id,
                redis=redis,
                request_id=request_id,
                start=start,
                resolved_runtime=resolved_runtime,
                whatsapp_connection=whatsapp_connection,
                route_key=route_key,
                channel_route_id=channel_route_id,
            )

    async def _process_locked(
        self,
        *,
        phone: str,
        content: str,
        message_id: str,
        input_type: str,
        audio_media_id: str | None,
        interactive_id: str | None,
        quoted_id: str | None,
        redis,
        request_id: str,
        start: float,
        resolved_runtime: ResolvedAgentRuntime | None,
        whatsapp_connection: WhatsAppConnectionContext | None,
        route_key: str | None,
        channel_route_id: uuid.UUID | None,
    ) -> None:
        """
        Cuerpo principal del pipeline (ya con lock por usuario adquirido).

        Filosofía AGENTE: el mensaje va directo al agent loop, que conversa,
        razona y usa herramientas/bases según haga falta. No hay clasificador
        previo, ni menús, ni ramas de intent enlatadas. El único gate que
        permanece es el de SEGURIDAD (autorización del número y permisos de
        herramientas), que NO se relaja.
        """
        profile = resolved_runtime.profile if resolved_runtime is not None else None
        try:
            # Marcar el mensaje como leído + typing (feedback inmediato).
            if message_id:
                await whatsapp_service.mark_as_read(
                    message_id,
                    request_id=request_id,
                    connection=whatsapp_connection,
                )
                await whatsapp_service.show_typing(
                    message_id, connection=whatsapp_connection
                )

            async with AsyncSessionLocal() as db:
                try:
                    # -----------------------------------------------------------
                    # 1. Governance — verificar autorización
                    # -----------------------------------------------------------
                    access = await governance_service.check_access(
                        db,
                        AccessCheckRequest(
                            request_id=request_id,
                            phone_number=phone,
                            channel="whatsapp",
                            agent_id=profile.id if profile is not None else None,
                        ),
                    )

                    if not access.allowed:
                        # Cargar perfil solo para el mensaje de rechazo
                        if profile is None:
                            profile = await agent_profile_service.get_active_profile(
                                db, redis
                            )
                        rejection_msg = (
                            profile.unauthorized_message
                            if profile
                            else "Tu número no está autorizado para usar este asistente."
                        )
                        logger.info(
                            "pipeline_access_denied",
                            extra={
                                "request_id": request_id,
                                "phone": phone,
                                "reason": access.reason,
                            },
                        )
                        await whatsapp_service.send_text_message(
                            phone=phone,
                            text=rejection_msg,
                            request_id=request_id,
                            connection=whatsapp_connection,
                        )
                        await self._finalize_pipeline(
                            db=db,
                            redis=redis,
                            phone=phone,
                            content=content,
                            response_text=rejection_msg,
                            request_id=request_id,
                            input_type=input_type,
                            start=start,
                            intent="access_denied",
                            source_system="internal",
                            tool_used=None,
                            status="blocked",
                            persist_conversation=False,
                            error_code="access_denied",
                            error_message=access.reason,
                            resolved_runtime=resolved_runtime,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                        )
                        return

                    # Fail-closed: contrato del schema dice que allowed=True implica user dict.
                    # Si llega allowed=True con user=None, es una inconsistencia de
                    # governance_service y NO debemos asumir nada permisivo.
                    if access.user is None:
                        logger.error(
                            "pipeline_access_check_inconsistent_failing_closed",
                            extra={"request_id": request_id, "phone": phone},
                        )
                        if profile is None:
                            profile = await agent_profile_service.get_active_profile(
                                db, redis
                            )
                        msg_err = (
                            profile.error_message
                            if profile
                            else (
                                "No pudimos verificar tu acceso en este momento. Intentá de nuevo en unos minutos."
                            )
                        )
                        await whatsapp_service.send_text_message(
                            phone=phone,
                            text=msg_err,
                            request_id=request_id,
                            connection=whatsapp_connection,
                        )
                        await self._finalize_pipeline(
                            db=db,
                            redis=redis,
                            phone=phone,
                            content=content,
                            response_text=msg_err,
                            request_id=request_id,
                            input_type=input_type,
                            start=start,
                            intent="access_check_inconsistent",
                            source_system="internal",
                            tool_used=None,
                            status="error",
                            persist_conversation=False,
                            error_code="access_user_missing",
                            error_message="check_access devolvió allowed=True sin user",
                            resolved_runtime=resolved_runtime,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                        )
                        return

                    # Identidad del usuario (ya verificada: exigimos user no nulo
                    # cuando allowed=True). Sin permisos por tool: el agente es uno
                    # para todos los usuarios autorizados.
                    import uuid as _uuid

                    user_id = _uuid.UUID(access.user["user_id"])

                    # -----------------------------------------------------------
                    # 1b. Configuración — verificar que el agente está configurado
                    # -----------------------------------------------------------
                    config_status = (
                        await configuration_service.check(db)
                        if resolved_runtime is None
                        else None
                    )
                    if config_status is not None and not config_status.is_ready:
                        errors = [
                            i.message
                            for i in config_status.issues
                            if i.level == "error"
                        ]
                        logger.warning(
                            "pipeline_configuration_error",
                            extra={
                                "request_id": request_id,
                                "phone": phone,
                                "issues": errors,
                            },
                        )
                        config_msg = (
                            "⚠️ El asistente no está completamente configurado. "
                            "Un administrador debe completar la configuración desde el panel."
                        )
                        await whatsapp_service.send_text_message(
                            phone=phone,
                            text=config_msg,
                            request_id=request_id,
                            connection=whatsapp_connection,
                        )
                        await self._finalize_pipeline(
                            db=db,
                            redis=redis,
                            phone=phone,
                            content=content,
                            response_text=config_msg,
                            request_id=request_id,
                            input_type=input_type,
                            start=start,
                            intent="configuration_error",
                            source_system="internal",
                            tool_used=None,
                            status="error",
                            persist_conversation=False,
                            error_code="configuration_error",
                            error_message="; ".join(errors),
                            resolved_runtime=resolved_runtime,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                        )
                        return

                    # -----------------------------------------------------------
                    # 2. AgentProfile — cargar identidad y system prompt del agente configurado
                    # -----------------------------------------------------------
                    if profile is None:
                        profile = await agent_profile_service.get_active_profile(
                            db, redis
                        )

                    # -----------------------------------------------------------
                    # 2b. Memoria — ventana activa + resumen rodante de largo plazo
                    # (continuidad más allá de la ventana de los últimos mensajes).
                    # -----------------------------------------------------------
                    if resolved_runtime is not None:
                        from app.services.chat_application import (
                            chat_application_service,
                        )

                        (
                            openai_history,
                            conversation_summary,
                        ) = await chat_application_service.load_whatsapp_context(
                            db,
                            agent_id=profile.id,
                            external_subject=phone,
                            limit=resolved_runtime.config.history_message_limit,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                        )
                    else:
                        conv_window = await conversation_service.load_window(
                            phone, db, redis
                        )
                        openai_history = conversation_service.build_openai_messages(
                            conv_window
                        )
                        conversation_summary = await conversation_service.get_summary(
                            db, phone
                        )

                    # -----------------------------------------------------------
                    # 2c. Transcripción de audio
                    # Si es una nota de voz, descargar de Meta y transcribir
                    # con Whisper. El texto resultante sigue el pipeline normal.
                    # Si falla, responder con mensaje de fallback amigable.
                    # -----------------------------------------------------------
                    if input_type == "audio":
                        # P2.1: commit antes de la transcripción con Whisper
                        # (puede tardar varios segundos descargando + transcribiendo).
                        # Liberamos la conexión DB al pool mientras hacemos I/O
                        # externo; SQLAlchemy adquirirá una nueva en la próxima query.
                        await db.commit()
                        if not audio_media_id:
                            logger.warning(
                                "pipeline_audio_no_media_id",
                                extra={"request_id": request_id, "phone": phone},
                            )
                            fallback = (
                                "No pude acceder al audio que enviaste. "
                                "¿Podés escribir tu consulta?"
                            )
                            await whatsapp_service.send_text_message(
                                phone=phone,
                                text=fallback,
                                request_id=request_id,
                                connection=whatsapp_connection,
                            )
                            await self._finalize_pipeline(
                                db=db,
                                redis=redis,
                                phone=phone,
                                content=content,
                                response_text=fallback,
                                request_id=request_id,
                                input_type=input_type,
                                start=start,
                                intent="audio_error",
                                source_system="internal",
                                tool_used=None,
                                status="error",
                                persist_conversation=False,
                                error_code="audio_no_media_id",
                                resolved_runtime=resolved_runtime,
                                route_key=route_key,
                                channel_route_id=channel_route_id,
                            )
                            return

                        transcript = (
                            await transcription_service.download_and_transcribe(
                                media_id=audio_media_id,
                                request_id=request_id,
                                connection=whatsapp_connection,
                                runtime=resolved_runtime,
                            )
                        )

                        if not transcript:
                            logger.warning(
                                "pipeline_audio_transcription_failed",
                                extra={
                                    "request_id": request_id,
                                    "phone": phone,
                                    "media_id": audio_media_id,
                                },
                            )
                            fallback = (
                                "No pude entender el audio que enviaste. "
                                "¿Podés repetirlo o escribir tu consulta?"
                            )
                            await whatsapp_service.send_text_message(
                                phone=phone,
                                text=fallback,
                                request_id=request_id,
                                connection=whatsapp_connection,
                            )
                            await self._finalize_pipeline(
                                db=db,
                                redis=redis,
                                phone=phone,
                                content=content,
                                response_text=fallback,
                                request_id=request_id,
                                input_type=input_type,
                                start=start,
                                intent="audio_error",
                                source_system="internal",
                                tool_used=None,
                                status="error",
                                persist_conversation=False,
                                error_code="audio_transcription_failed",
                                resolved_runtime=resolved_runtime,
                                route_key=route_key,
                                channel_route_id=channel_route_id,
                            )
                            return

                        logger.info(
                            "pipeline_audio_transcribed",
                            extra={
                                "request_id": request_id,
                                "phone": phone,
                                "chars": len(transcript),
                                "preview": transcript[:80],
                            },
                        )
                        # Reemplazar el placeholder con el texto real transcripto.
                        # El pipeline continúa desde aquí exactamente igual que con texto.
                        content = transcript

                    # -----------------------------------------------------------
                    # 2d. Tipos no soportados (imagen, video, archivo)
                    # Audio ya fue manejado en 2c.
                    # -----------------------------------------------------------
                    if input_type in ("image", "video", "file"):
                        unsupported_msg = (
                            "Por ahora no puedo abrir imágenes, videos ni archivos 🙅. "
                            "Si me contás qué necesitás por texto, lo resuelvo."
                        )
                        logger.info(
                            "pipeline_unsupported_input",
                            extra={
                                "request_id": request_id,
                                "phone": phone,
                                "input_type": input_type,
                            },
                        )
                        await whatsapp_service.send_text_message(
                            phone=phone,
                            text=unsupported_msg,
                            request_id=request_id,
                            connection=whatsapp_connection,
                        )
                        await self._finalize_pipeline(
                            db=db,
                            redis=redis,
                            phone=phone,
                            content=content,
                            response_text=unsupported_msg,
                            request_id=request_id,
                            input_type=input_type,
                            start=start,
                            intent="unsupported_input",
                            source_system="unsupported",
                            tool_used=None,
                            status="unsupported",
                            persist_conversation=True,
                            resolved_runtime=resolved_runtime,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                        )
                        return

                    # -----------------------------------------------------------
                    # 3. Tools disponibles: habilitadas en DB ∩ registradas en
                    # runtime. Sin permisos por usuario: el agente es uno para todos.
                    # -----------------------------------------------------------
                    try:
                        from app.services.tools.dynamic import sync_http_api_tools

                        await sync_http_api_tools(db)
                    except Exception as e:
                        logger.warning(
                            "http_api_tools_sync_before_pipeline_failed",
                            extra={
                                "request_id": request_id,
                                "phone": phone,
                                "error": str(e),
                            },
                        )

                    runtime_tools = set(tool_registry.list_tools())
                    from app.schemas.tools import ToolExecutionContext
                    from app.services.tool_policy import tool_policy_service

                    execution_context = ToolExecutionContext(
                        request_id=request_id,
                        channel="whatsapp",
                        principal_id=str(user_id) if user_id else None,
                        agent_id=str(profile.id) if profile is not None else None,
                        external_subject=phone,
                        scopes={"tools:read", "tools:write"},
                    )
                    available_tools = await tool_policy_service.available_tools(
                        db,
                        execution_context,
                        runtime_tools,
                    )
                    # Cargar params_schema de cada tool habilitada (para las
                    # function definitions de OpenAI).
                    all_tool_configs_result = await db.execute(
                        select(ToolConfig).where(
                            ToolConfig.is_enabled == True,  # noqa: E712
                            ToolConfig.tool_name.in_(
                                [item["tool_name"] for item in available_tools]
                            ),
                        )
                    )
                    tool_configs = {
                        t.tool_name: {
                            "params_schema": t.params_schema or {},
                            "timeout_seconds": t.timeout_seconds,
                        }
                        for t in all_tool_configs_result.scalars().all()
                    }

                    logger.info(
                        "pipeline_available_tools_for_user",
                        extra={
                            "request_id": request_id,
                            "phone": phone,
                            "count": len(available_tools),
                        },
                    )

                    # Commit antes del agent loop (libera la conexión DB durante
                    # las llamadas externas, que pueden tardar).
                    await db.commit()

                    if message_id:
                        await whatsapp_service.show_typing(
                            message_id, connection=whatsapp_connection
                        )

                    # Contexto de mensaje citado (reply): si el usuario respondió
                    # citando un mensaje nuestro, resolvemos su texto (guardado por
                    # wamid) para que el agente sepa a qué se refiere
                    # ("¿cómo obtuviste este dato?").
                    if quoted_id and redis is not None:
                        try:
                            quote_scope = route_key or "legacy"
                            quoted_text = await redis.get(
                                f"wamsg:{quote_scope}:{quoted_id}"
                            )
                        except Exception:
                            quoted_text = None
                        if quoted_text:
                            content = (
                                f"[El usuario respondió citando tu mensaje anterior: "
                                f'"{quoted_text[:400]}"]\n\n{content}'
                            )

                    # -----------------------------------------------------------
                    # 4. AGENT LOOP — único cerebro: conversa, razona y usa
                    # herramientas/bases según haga falta. Sin clasificador,
                    # sin menús, sin ramas enlatadas.
                    # -----------------------------------------------------------
                    from app.services.agent_loop import run_agent_loop

                    agent_result = await run_agent_loop(
                        user_message=content,
                        conversation_history=openai_history,
                        available_tools=available_tools,
                        tool_configs=tool_configs,
                        profile=profile,
                        user_id=user_id,
                        phone=phone,
                        request_id=request_id,
                        db=db,
                        conversation_summary=conversation_summary,
                        execution_context=execution_context,
                        runtime=resolved_runtime,
                    )

                    response_text = agent_result.response_text

                    # -----------------------------------------------------------
                    # 5. Archivos producidos durante el loop (imágenes/Excel)
                    # -----------------------------------------------------------
                    for agent_file in agent_result.files:
                        try:
                            if agent_file.storage_key:
                                from app.services.rag.storage import document_storage

                                media_id = await whatsapp_service.upload_media_path(
                                    file_path=document_storage.path_for(
                                        agent_file.storage_key
                                    ),
                                    filename=agent_file.name,
                                    mime_type=agent_file.mime,
                                    request_id=request_id,
                                    connection=whatsapp_connection,
                                )
                            elif agent_file.content is not None:
                                media_id = await whatsapp_service.upload_media(
                                    file_bytes=agent_file.content,
                                    filename=agent_file.name,
                                    mime_type=agent_file.mime,
                                    request_id=request_id,
                                    connection=whatsapp_connection,
                                )
                            else:
                                media_id = None
                            if media_id:
                                if agent_file.mime.startswith("image/"):
                                    await whatsapp_service.send_image_message(
                                        phone=phone,
                                        media_id=media_id,
                                        request_id=request_id,
                                        connection=whatsapp_connection,
                                    )
                                else:
                                    await whatsapp_service.send_document_message(
                                        phone=phone,
                                        media_id=media_id,
                                        filename=agent_file.name,
                                        request_id=request_id,
                                        connection=whatsapp_connection,
                                    )
                                logger.info(
                                    "pipeline_file_sent",
                                    extra={
                                        "request_id": request_id,
                                        "file_name": agent_file.name,
                                        "phone": phone,
                                    },
                                )
                        except Exception as file_exc:
                            logger.error(
                                "pipeline_file_send_error",
                                extra={
                                    "request_id": request_id,
                                    "error": str(file_exc),
                                },
                            )

                    # -----------------------------------------------------------
                    # 6. Enviar la respuesta del agente (sin botones de menú)
                    # -----------------------------------------------------------
                    sent_wamid = await whatsapp_service.send_text_message(
                        phone=phone,
                        text=response_text,
                        request_id=request_id,
                        connection=whatsapp_connection,
                    )
                    # Guardar el texto enviado por wamid para poder resolver
                    # futuras respuestas citadas del usuario (ver quoted_id).
                    if sent_wamid and redis is not None:
                        try:
                            await redis.setex(
                                f"wamsg:{route_key or 'legacy'}:{sent_wamid}",
                                86400,
                                response_text[:1000],
                            )
                        except Exception as e:
                            logger.debug(
                                "wamsg_store_failed",
                                extra={"request_id": request_id, "error": str(e)},
                            )

                    # -----------------------------------------------------------
                    # 7. Memoria — persistir la conversación
                    # -----------------------------------------------------------
                    tools_str = (
                        ",".join(agent_result.tools_used)
                        if agent_result.tools_used
                        else None
                    )
                    if resolved_runtime is None:
                        await conversation_service.save_messages(
                            phone,
                            content,
                            response_text,
                            db,
                            redis,
                            intent="agent",
                            tool_used=tools_str,
                        )
                    from app.services.chat_application import chat_application_service

                    await chat_application_service.record_whatsapp_exchange(
                        db,
                        profile=profile,
                        request_id=request_id,
                        external_subject=phone,
                        user_content=content,
                        assistant_content=response_text,
                        tools_used=list(agent_result.tools_used),
                        display_name=access.user.get("name") if access.user else None,
                        route_key=route_key,
                        channel_route_id=channel_route_id,
                    )

                    # -----------------------------------------------------------
                    # 8. Audit
                    # -----------------------------------------------------------
                    await self._log_audit(
                        db,
                        request_id=request_id,
                        phone=phone,
                        input_type=input_type,
                        intent="agent",
                        source_system="dynamic",
                        tool_used=tools_str,
                        status=agent_result.status,
                        response_preview=response_text[:500],
                        duration_ms=int((time.monotonic() - start) * 1000),
                        user_message=content,
                        tool_calls=agent_result.tool_invocations,
                        extra_metadata={"rag_hits": agent_result.rag_hits},
                    )

                    await db.commit()

                    # Memoria nivel 3: refrescar el resumen rodante si hay mensajes
                    # que envejecieron fuera de la ventana. Best-effort y post-respuesta
                    # (no agrega latencia perceptible); usa su propia sesión DB.
                    if resolved_runtime is None:
                        await conversation_service.maybe_update_summary(phone)

                    elapsed = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "pipeline_completed",
                        extra={
                            "request_id": request_id,
                            "phone": phone,
                            "tools": agent_result.tools_used,
                            "iterations": agent_result.iterations,
                            "tool_calls": agent_result.total_tool_calls,
                            "status": agent_result.status,
                            "duration_ms": elapsed,
                        },
                    )

                except Exception:
                    await db.rollback()
                    raise

        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error(
                "pipeline_error",
                extra={
                    "request_id": request_id,
                    "phone": phone,
                    "error": str(e),
                    "duration_ms": elapsed,
                },
                exc_info=True,
            )
            try:
                if profile is None:
                    async with AsyncSessionLocal() as db_err:
                        profile = await agent_profile_service.get_active_profile(
                            db_err, redis
                        )
                error_msg = (
                    profile.error_message
                    if profile
                    else (
                        "⚠️ Ocurrió un error procesando tu mensaje. Por favor intentá de nuevo más tarde."
                    )
                )
                await whatsapp_service.send_text_message(
                    phone=phone,
                    text=error_msg,
                    request_id=request_id,
                    connection=whatsapp_connection,
                )
            except Exception:
                logger.error(
                    "pipeline_error_notification_failed",
                    extra={"request_id": request_id},
                )

    async def _log_audit(
        self,
        db,
        *,
        request_id,
        phone,
        input_type,
        intent,
        source_system,
        tool_used,
        status,
        response_preview,
        duration_ms,
        error_code: str | None = None,
        error_message: str | None = None,
        user_message: str | None = None,
        tool_calls: list | None = None,
        extra_metadata: dict | None = None,
    ) -> None:
        """Registra la auditoría de la interacción."""
        try:
            # Normalizar source_system a string. El schema acepta SourceSystemEnum,
            # pero recibimos a veces el value como str cuando se construye desde JSON.
            ss_value = source_system
            if ss_value is not None and not hasattr(ss_value, "value"):
                # Es string: convertir a enum si es válido
                try:
                    from app.schemas.common import SourceSystemEnum

                    ss_value = SourceSystemEnum(ss_value)
                except Exception:
                    ss_value = None
            await audit_service.log(
                db,
                AuditLogCreate(
                    request_id=request_id,
                    phone_number=phone,
                    channel=ChannelEnum.whatsapp,
                    input_type=InputTypeEnum(input_type),
                    intent=intent,
                    source_system=ss_value,
                    tool_used=tool_used,
                    duration_ms=duration_ms,
                    status=StatusEnum(status),
                    response_preview=response_preview,
                    error_code=error_code,
                    error_message=error_message,
                    user_message=user_message,
                    tool_calls=tool_calls or [],
                    extra_metadata=extra_metadata or {},
                ),
            )
        except Exception as e:
            logger.error(
                "pipeline_audit_error",
                extra={"request_id": request_id, "error": str(e)},
            )

    async def _finalize_pipeline(
        self,
        *,
        db,
        redis,
        phone: str,
        content: str,
        response_text: str,
        request_id: str,
        input_type: str,
        start: float,
        intent: str,
        source_system: str | None,
        tool_used: str | None,
        status: str,
        persist_conversation: bool = True,
        error_code: str | None = None,
        error_message: str | None = None,
        resolved_runtime: ResolvedAgentRuntime | None = None,
        route_key: str | None = None,
        channel_route_id: uuid.UUID | None = None,
    ) -> None:
        """
        Cierre uniforme de exit paths del pipeline.

        Para cualquier salida del pipeline (acceso denegado, audio fallido,
        tool no encontrada, timeout, out-of-domain, etc.) este helper:
          1. Persiste el par (user_message, assistant_response) en conversation
             (opcional, por defecto activo).
          2. Registra el evento en audit_logs con todos los metadatos.
          3. Hace commit de la sesión DB.

        Esto garantiza trazabilidad completa de qué sucedió con cada mensaje,
        incluso en ramas que antes salían sin guardar nada.
        """
        try:
            if persist_conversation:
                try:
                    if resolved_runtime is not None:
                        from app.services.chat_application import (
                            chat_application_service,
                        )

                        await chat_application_service.record_whatsapp_exchange(
                            db,
                            profile=resolved_runtime.profile,
                            request_id=request_id,
                            external_subject=phone,
                            user_content=content,
                            assistant_content=response_text,
                            tools_used=[tool_used] if tool_used else [],
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                        )
                    else:
                        await conversation_service.save_messages(
                            phone,
                            content,
                            response_text,
                            db,
                            redis,
                            intent=intent,
                            tool_used=tool_used,
                        )
                except Exception as e:
                    logger.warning(
                        "pipeline_finalize_conversation_save_failed",
                        extra={
                            "request_id": request_id,
                            "phone": phone,
                            "error": str(e),
                        },
                    )
            await self._log_audit(
                db,
                request_id=request_id,
                phone=phone,
                input_type=input_type,
                intent=intent,
                source_system=source_system,
                tool_used=tool_used,
                status=status,
                response_preview=response_text[:500] if response_text else None,
                duration_ms=int((time.monotonic() - start) * 1000),
                error_code=error_code,
                error_message=error_message,
                user_message=content,
            )
            await db.commit()
        except Exception as e:
            logger.error(
                "pipeline_finalize_failed",
                extra={"request_id": request_id, "phone": phone, "error": str(e)},
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass


pipeline_service = PipelineService()
