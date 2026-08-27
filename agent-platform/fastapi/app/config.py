"""Infrastructure configuration for the channel-neutral agent platform."""

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
    default_agent_slug: str = "saltacode"
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
