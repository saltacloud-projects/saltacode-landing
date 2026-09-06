"""Infrastructure configuration for the channel-neutral agent platform."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Entorno
    fastapi_env: str = "production"
    log_level: str = "INFO"

    # Versión de la aplicación (leida desde APP_VERSION en .env / docker-compose)
    app_version: str = "1.0.0"

    # Base de datos
    postgres_dsn: str

    # Redis
    redis_url: str = "redis://redis:6379"

    # Seguridad — API key para autenticar llamadas internas
    fastapi_api_key: str

    # Dominio público (para TrustedHostMiddleware en producción)
    domain: str = "localhost"

    # ---------------------------------------------------------------------------
    # WhatsApp — Meta Cloud API
    # ---------------------------------------------------------------------------
    # Token de acceso de la app en Meta Business Suite
    whatsapp_token: str = ""
    # ID del número de teléfono registrado en Meta
    whatsapp_phone_number_id: str = ""
    # Token secreto para verificar el webhook (lo elegís vos, se configura en Meta)
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    channel_inbound_worker_id: str = Field(
        default="channel-inbound-worker-1",
        min_length=1,
        max_length=70,
        validation_alias=AliasChoices(
            "CHANNEL_INBOUND_WORKER_ID", "WHATSAPP_INBOX_WORKER_ID"
        ),
    )
    channel_inbound_poll_seconds: float = Field(
        default=1.0,
        gt=0,
        le=60,
        validation_alias=AliasChoices(
            "CHANNEL_INBOUND_POLL_SECONDS", "WHATSAPP_INBOX_POLL_SECONDS"
        ),
    )
    # Runtime loop_timeout is capped at 900s; keep a recovery margin above it.
    channel_inbound_lease_seconds: int = Field(
        default=1200,
        ge=960,
        le=86_400,
        validation_alias=AliasChoices(
            "CHANNEL_INBOUND_LEASE_SECONDS", "WHATSAPP_INBOX_STALE_SECONDS"
        ),
    )
    outbound_worker_id: str = Field(
        default="outbound-worker-1", min_length=1, max_length=70
    )
    outbound_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    outbound_worker_max_backoff_seconds: float = Field(default=30.0, ge=1, le=300)
    outbound_dispatch_stale_seconds: int = Field(default=300, ge=60, le=86_400)
    follow_up_worker_id: str = Field(
        default="follow-up-worker-1", min_length=1, max_length=70
    )
    follow_up_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    follow_up_worker_max_backoff_seconds: float = Field(default=30.0, ge=1, le=300)
    follow_up_execution_lease_seconds: int = Field(default=120, ge=30, le=3_600)
    web_execution_worker_id: str = Field(
        default="web-execution-worker-1", min_length=1, max_length=70
    )
    web_execution_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    web_execution_worker_max_backoff_seconds: float = Field(default=30.0, ge=1, le=300)
    # Persisted agent runtimes permit a 900-second loop timeout. A worker must
    # retain ownership longer than that maximum or valid results become stale.
    web_execution_lease_seconds: int = Field(default=1200, gt=900, le=86_400)

    # ---------------------------------------------------------------------------
    # OpenAI
    # ---------------------------------------------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_whisper_model: str = "whisper-1"  # Modelo de transcripción de audio

    # RAG — los parámetros operativos viven en PostgreSQL; estas rutas son
    # infraestructura del container y por eso permanecen en entorno.
    document_storage_root: str = "/data/documents"
    rag_worker_id: str = "rag-worker-1"
    rag_worker_poll_seconds: float = 2.0

    # ---------------------------------------------------------------------------
    # Dynamic source credentials live encrypted in PostgreSQL. Only the root
    # encryption key remains outside the database and admin panel.
    credential_encryption_key_file: str = "/run/agent-secrets/source_master.key"
    contact_encryption_key_file: str = "/run/agent-secrets/contact_data.key"
    contact_lookup_hmac_key_file: str = "/run/agent-secrets/contact_lookup_hmac.key"
    default_agent_slug: str = "saltacode"
    agent_web_route_key: str = "saltacode-landing"
    agent_web_external_account_id: str = ""
    retention_sweep_interval_seconds: int = 21_600

    # ---------------------------------------------------------------------------
    # Admin panel — JWT + usuario inicial
    # ---------------------------------------------------------------------------
    jwt_secret_key: str = "CHANGE-ME-IN-PRODUCTION"  # openssl rand -hex 32
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    admin_frontend_url: str = "http://localhost:3000"
    admin_initial_email: str = "admin@agent.local"
    admin_initial_password: str = ""  # local bootstrap only; use a secret in production

    # ---------------------------------------------------------------------------
    # Memoria conversacional — resumen rodante de largo plazo (nivel 3)
    # Cuando los mensajes envejecen fuera de la ventana activa, se compactan en un
    # resumen por usuario (AuthorizedUser.conversation_summary) que se inyecta al
    # prompt para dar continuidad más allá de la ventana.
    # ---------------------------------------------------------------------------
    memory_summary_enabled: bool = True
    # Cantidad de mensajes "envejecidos" (fuera de la ventana) que se acumulan
    # antes de refrescar el resumen. Mayor = menos llamadas al LLM y memoria más
    # gruesa; menor = memoria más fina pero más costo.
    memory_summary_trigger_messages: int = 10
    # Tope de caracteres del resumen persistido (se trunca si el LLM se excede).
    memory_summary_max_chars: int = 60000


# Instancia global (singleton)
settings = Settings()
