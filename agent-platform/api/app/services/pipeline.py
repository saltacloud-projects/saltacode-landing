"""
Agent Platform — PipelineService
Orquesta el procesamiento de un mensaje de WhatsApp con filosofía de AGENTE:
  1. Governance  — verificar autorización del número (gate de seguridad)
  2. AgentProfile — cargar identidad/personalidad del agente
  3. Memoria     — cargar ventana de conversación
  4. Audio       — transcribir notas de voz (Whisper)
  5. Tools       — cargar herramientas disponibles (incluye DB para superusuarios)
  6. Agent Loop  — cerebro único: conversa, razona y usa herramientas/bases
  7. Response    — persistir respuesta + comandos outbound durables
  8. Memoria/Audit — persistir conversación y auditar

No hay clasificador, menús, ni ramas de intent enlatadas: el agente maneja
todo. El único gate que permanece es el de seguridad (auth + permisos).
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from app.core.concurrency import pipeline_semaphore
from app.core.database import AsyncSessionLocal
from app.core.dedup_lock import conversation_lock
from app.models.outbound import OutboundMessage
from app.models.platform import ChatMessage
from app.models.tool_config import ToolConfig
from app.schemas.audit import AuditLogCreate
from app.schemas.common import ChannelEnum, InputTypeEnum, StatusEnum
from app.schemas.inbound import InboundMessageEnvelope
from app.services.agent_loop import run_agent_loop
from app.services.agent_runtime import ResolvedAgentRuntime
from app.services.audit import audit_service
from app.services.chat_application import chat_application_service
from app.services.conversation_control import (
    AutomationBlockedError,
    ControlVersionConflictError,
    conversation_control_service,
)
from app.services.inbound import (
    InboundAccessDenied,
    InboundAccessPolicyError,
    inbound_access_policy,
)
from app.services.tools.registry import tool_registry
from app.services.transcription import transcription_service
from app.services.whatsapp import WhatsAppConnectionContext, whatsapp_service

logger = logging.getLogger(__name__)
AutomationGuard = Callable[[], Awaitable[None]]


class PipelineFinalizationFailed(RuntimeError):
    """Conversation or audit state could not be committed durably."""


class PipelineService:
    async def process_whatsapp_message(
        self,
        *,
        message: InboundMessageEnvelope,
        redis=None,
        resolved_runtime: ResolvedAgentRuntime,
        whatsapp_connection: WhatsAppConnectionContext,
        request_id: str | None = None,
        propagate_errors: bool = False,
        notify_on_error: bool = True,
    ) -> None:
        """
        Pipeline completo de procesamiento de un mensaje entrante.
        Ejecuta en background — no bloquea la respuesta HTTP a Meta.

        Para mensajes de audio: descarga y transcribe con Whisper antes
        de continuar el flujo normal como si fuera texto.

        Para selecciones de menú interactivo (`interactive_id` presente):
        enruta determinísticamente según el id antes de involucrar al LLM.
        """
        if message.channel != "whatsapp":
            raise ValueError("WhatsApp pipeline requires a WhatsApp envelope")
        if (
            whatsapp_connection.connection_id != message.route.channel_connection_id
            or whatsapp_connection.route_key != message.route.route_key
        ):
            raise ValueError("WhatsApp envelope does not match its resolved connection")
        request_id = request_id or str(message.correlation_id)
        phone = message.provider_sender_id
        content = message.content
        message_id = message.provider_message_id
        input_type = message.content_type.value
        audio_media_id = message.provider_media_id
        interactive_id = message.interaction_id
        quoted_id = (
            message.reply_context.provider_message_id
            if message.reply_context is not None
            else None
        )
        route_key = message.route.route_key
        channel_route_id = message.route.channel_route_id
        start = time.monotonic()

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
                propagate_errors=propagate_errors,
                notify_on_error=notify_on_error,
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
        propagate_errors: bool,
        notify_on_error: bool,
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
                propagate_errors=propagate_errors,
                notify_on_error=notify_on_error,
            )

    @staticmethod
    async def _resolve_quoted_text(
        db,
        *,
        quoted_id: str,
        agent_id: uuid.UUID,
        channel_route_id: uuid.UUID,
        route_key: str,
        redis,
    ) -> str | None:
        text = (
            await db.execute(
                select(ChatMessage.content)
                .join(
                    OutboundMessage,
                    OutboundMessage.chat_message_id == ChatMessage.id,
                )
                .where(
                    OutboundMessage.agent_id == agent_id,
                    OutboundMessage.channel_route_id == channel_route_id,
                    OutboundMessage.provider_message_id == quoted_id,
                )
            )
        ).scalar_one_or_none()
        if text is not None or redis is None:
            return text
        try:
            cached = await redis.get(f"wamsg:{route_key}:{quoted_id}")
        except Exception:
            return None
        return cached if isinstance(cached, str) else None

    @staticmethod
    def _build_automation_guard(
        *,
        conversation_id: uuid.UUID,
        agent_id: uuid.UUID,
        control_version: int,
    ) -> AutomationGuard:
        async def guard() -> None:
            async with AsyncSessionLocal() as control_db:
                await conversation_control_service.assert_automation_allowed(
                    control_db,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    expected_version=control_version,
                )

        return guard

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
        propagate_errors: bool,
        notify_on_error: bool,
    ) -> None:
        """
        Cuerpo principal del pipeline (ya con lock por usuario adquirido).

        Filosofía AGENTE: el mensaje va directo al agent loop, que conversa,
        razona y usa herramientas/bases según haga falta. No hay clasificador
        previo, ni menús, ni ramas de intent enlatadas. El único gate que
        permanece es el de SEGURIDAD (autorización del número y permisos de
        herramientas), que NO se relaja.
        """
        if resolved_runtime is None:
            raise PipelineFinalizationFailed(
                "WhatsApp processing requires a persisted route"
            )
        profile = resolved_runtime.profile
        automation_guard: AutomationGuard | None = None
        control_version: int | None = None
        try:
            # Marcar el mensaje como leído + typing (feedback inmediato).
            if message_id:
                await whatsapp_service.mark_as_read(
                    message_id,
                    request_id=request_id,
                    connection=whatsapp_connection,
                )

            async with AsyncSessionLocal() as db:
                try:
                    (
                        openai_history,
                        conversation_summary,
                        controlled_conversation,
                    ) = await chat_application_service.load_whatsapp_context(
                        db,
                        agent_id=profile.id,
                        external_subject=phone,
                        limit=resolved_runtime.config.history_message_limit,
                        route_key=route_key,
                        channel_route_id=channel_route_id,
                        history_cache_ttl_seconds=resolved_runtime.config.history_cache_ttl_seconds,
                        redis=redis,
                    )
                    control_version = controlled_conversation.control_version
                    automation_guard = self._build_automation_guard(
                        conversation_id=controlled_conversation.id,
                        agent_id=profile.id,
                        control_version=control_version,
                    )
                    await db.commit()

                    try:
                        inbound_identity = await inbound_access_policy.resolve(
                            db,
                            profile=profile,
                            conversation=controlled_conversation,
                            sender_id=phone,
                            request_id=request_id,
                            channel="whatsapp",
                        )
                    except InboundAccessDenied as exc:
                        await automation_guard()
                        rejection_msg = profile.unauthorized_message
                        logger.info(
                            "pipeline_access_denied",
                            extra={
                                "request_id": request_id,
                                "phone": phone,
                                "reason": str(exc),
                            },
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
                            error_message=str(exc),
                            resolved_runtime=resolved_runtime,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                            control_version=control_version,
                            raise_on_error=propagate_errors,
                        )
                        return
                    except InboundAccessPolicyError:
                        logger.error(
                            "pipeline_access_check_inconsistent_failing_closed",
                            extra={"request_id": request_id, "phone": phone},
                        )
                        await automation_guard()
                        msg_err = profile.error_message
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
                            error_message="access policy returned an invalid identity",
                            resolved_runtime=resolved_runtime,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                            control_version=control_version,
                            raise_on_error=propagate_errors,
                        )
                        return
                    user_id = inbound_identity.user_id

                    # Make the inbound visible to a human operator before any
                    # automation guard can stop this execution. A retry reuses
                    # the same provider-scoped request id.
                    await chat_application_service.record_whatsapp_inbound(
                        db,
                        conversation=controlled_conversation,
                        request_id=request_id,
                        content=content,
                    )
                    await db.commit()
                    await automation_guard()

                    # -----------------------------------------------------------
                    # 2b. Memoria — ventana activa + resumen rodante de largo plazo
                    # (continuidad más allá de la ventana de los últimos mensajes).
                    # -----------------------------------------------------------
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
                                control_version=control_version,
                                raise_on_error=propagate_errors,
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
                                control_version=control_version,
                                raise_on_error=propagate_errors,
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
                            control_version=control_version,
                            raise_on_error=propagate_errors,
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
                                "error_type": type(e).__name__,
                            },
                        )

                    runtime_tools = set(tool_registry.list_tools())
                    from app.schemas.tools import ToolExecutionContext
                    from app.services.tool_policy import tool_policy_service

                    execution_context = ToolExecutionContext(
                        request_id=request_id,
                        channel="whatsapp",
                        principal_id=str(inbound_identity.principal_id),
                        conversation_id=str(controlled_conversation.id),
                        agent_id=str(profile.id),
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

                    if automation_guard is not None:
                        await automation_guard()
                    if message_id:
                        await whatsapp_service.show_typing(
                            message_id, connection=whatsapp_connection
                        )

                    # Contexto de mensaje citado (reply): si el usuario respondió
                    # citando un mensaje nuestro, resolvemos su texto (guardado por
                    # wamid) para que el agente sepa a qué se refiere
                    # ("¿cómo obtuviste este dato?").
                    if quoted_id:
                        quoted_text = await self._resolve_quoted_text(
                            db,
                            quoted_id=quoted_id,
                            agent_id=profile.id,
                            channel_route_id=channel_route_id,
                            route_key=route_key,
                            redis=redis,
                        )
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
                        automation_guard=automation_guard,
                    )
                    if automation_guard is not None:
                        await automation_guard()

                    response_text = agent_result.response_text

                    # Persist the neutral exchange and every outbound command in
                    # one transaction. Provider I/O belongs only to the worker.
                    tools_str = (
                        ",".join(agent_result.tools_used)
                        if agent_result.tools_used
                        else None
                    )
                    await chat_application_service.record_whatsapp_exchange(
                        db,
                        profile=profile,
                        request_id=request_id,
                        external_subject=phone,
                        user_content=content,
                        assistant_content=response_text,
                        tools_used=list(agent_result.tools_used),
                        display_name=inbound_identity.display_name,
                        route_key=route_key,
                        channel_route_id=channel_route_id,
                        control_version=control_version,
                        outbound_files=list(agent_result.files),
                        runtime=resolved_runtime,
                        redis=redis,
                    )

                    # -----------------------------------------------------------
                    # 8. Audit
                    # -----------------------------------------------------------
                    await self._log_audit(
                        db,
                        agent_id=profile.id,
                        channel_route_id=channel_route_id,
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
                        raise_on_error=propagate_errors,
                    )

                    await db.commit()

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

        except (AutomationBlockedError, ControlVersionConflictError):
            logger.info(
                "pipeline_automation_blocked",
                extra={
                    "request_id": request_id,
                    "phone": phone,
                    "control_version": control_version,
                },
            )
            return
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.error(
                "pipeline_error",
                extra={
                    "request_id": request_id,
                    "phone": phone,
                    "error_type": type(e).__name__,
                    "duration_ms": elapsed,
                },
                exc_info=True,
            )
            if notify_on_error:
                try:
                    error_msg = (
                        profile.error_message
                        if profile
                        else (
                            "⚠️ Ocurrió un error procesando tu mensaje. Por favor intentá de nuevo más tarde."
                        )
                    )
                    if control_version is None:
                        raise PipelineFinalizationFailed(
                            "conversation control was not initialized"
                        )
                    if automation_guard is not None:
                        await automation_guard()
                    async with AsyncSessionLocal() as db_err:
                        await chat_application_service.record_whatsapp_notification(
                            db_err,
                            profile=resolved_runtime.profile,
                            request_id=request_id,
                            purpose="pipeline-error",
                            external_subject=phone,
                            content=error_msg,
                            route_key=route_key,
                            channel_route_id=channel_route_id,
                            control_version=control_version,
                        )
                        await db_err.commit()
                except (AutomationBlockedError, ControlVersionConflictError):
                    logger.info(
                        "pipeline_error_notification_blocked",
                        extra={
                            "request_id": request_id,
                            "phone": phone,
                            "control_version": control_version,
                        },
                    )
                except Exception:
                    logger.error(
                        "pipeline_error_notification_failed",
                        extra={"request_id": request_id},
                    )
            if propagate_errors:
                raise

    async def _log_audit(
        self,
        db,
        *,
        agent_id: uuid.UUID | None,
        channel_route_id: uuid.UUID | None,
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
        raise_on_error: bool = False,
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
                    agent_id=agent_id,
                    channel_route_id=channel_route_id,
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
                extra={"request_id": request_id, "error_type": type(e).__name__},
            )
            if raise_on_error:
                raise

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
        control_version: int | None = None,
        raise_on_error: bool = False,
    ) -> None:
        """
        Cierre uniforme de exit paths del pipeline.

        Para cualquier salida del pipeline (acceso denegado, audio fallido,
        tool no encontrada, timeout, out-of-domain, etc.) este helper:
          1. Persiste el mensaje visible y su comando outbound en la misma
             transacción; opcionalmente conserva también el inbound.
          2. Registra el evento en audit_logs con todos los metadatos.
          3. Hace commit antes de que el worker contacte al proveedor.

        Esto garantiza trazabilidad completa de qué sucedió con cada mensaje,
        incluso en ramas que antes salían sin guardar nada.
        """
        try:
            if (
                resolved_runtime is None
                or route_key is None
                or channel_route_id is None
                or control_version is None
            ):
                raise PipelineFinalizationFailed(
                    "WhatsApp finalization requires a persisted route and control epoch"
                )
            try:
                if persist_conversation:
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
                        control_version=control_version,
                        runtime=resolved_runtime,
                        redis=redis,
                    )
                else:
                    await chat_application_service.record_whatsapp_notification(
                        db,
                        profile=resolved_runtime.profile,
                        request_id=request_id,
                        purpose=intent,
                        external_subject=phone,
                        content=response_text,
                        route_key=route_key,
                        channel_route_id=channel_route_id,
                        control_version=control_version,
                    )
            except Exception as e:
                logger.warning(
                    "pipeline_finalize_conversation_save_failed",
                    extra={
                        "request_id": request_id,
                        "phone": phone,
                        "error_type": type(e).__name__,
                    },
                )
                raise
            await self._log_audit(
                db,
                agent_id=resolved_runtime.profile.id,
                channel_route_id=channel_route_id,
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
                raise_on_error=raise_on_error,
            )
            await db.commit()
        except Exception as e:
            logger.error(
                "pipeline_finalize_failed",
                extra={
                    "request_id": request_id,
                    "phone": phone,
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            if raise_on_error:
                raise PipelineFinalizationFailed(
                    "WhatsApp pipeline state could not be finalized"
                ) from e


pipeline_service = PipelineService()
