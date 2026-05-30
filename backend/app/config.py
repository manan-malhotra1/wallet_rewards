"""Application settings loaded from .env (via pydantic-settings)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Topics:
    """Kafka topic constants — single source of truth.

    Match the constants in infra/kafka/topics.sh.
    """

    TRANSACTIONS_COMPLETED = "wallet.transactions.completed"
    EVENTS_EXTERNAL = "wallet.events.external"
    EVENTS_NORMALISED = "wallet.events.normalised"
    REWARDS_ISSUED = "wallet.rewards.issued"
    ENGAGEMENT_OUTBOUND = "wallet.engagement.outbound"
    RECONCILIATION_PENDING = "wallet.reconciliation.pending"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    DATABASE_URL: str
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    REDIS_URL: str = "redis://localhost:6379/0"

    KEYCLOAK_URL: str
    KEYCLOAK_REALM: str
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_CLIENT_SECRET: str

    SECRET_KEY: str
    OTP_EXPIRY_SECONDS: int = 300
    PIN_MAX_ATTEMPTS: int = 5
    PIN_LOCKOUT_MINUTES: int = 30
    # Local-dev only: return the generated OTP in /otp/send response so tests
    # and manual demos can verify without an SMS gateway. MUST be False
    # outside local dev (NFR-0170 — OTPs are credentials and never leave the
    # server in production).
    OTP_DEV_RETURN: bool = True
    LOG_LEVEL: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
