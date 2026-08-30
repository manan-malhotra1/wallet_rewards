"""Application settings loaded from .env (via pydantic-settings)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Topics:
    """Kafka topic constants — single source of truth.

    Match the constants in sasai-wallet-infra/kafka/topics.sh.
    """

    TRANSACTIONS_COMPLETED = "wallet.transactions.completed"
    EVENTS_EXTERNAL = "wallet.events.external"
    EVENTS_NORMALISED = "wallet.events.normalised"
    REWARDS_ISSUED = "wallet.rewards.issued"
    ENGAGEMENT_OUTBOUND = "wallet.engagement.outbound"
    RECONCILIATION_PENDING = "wallet.reconciliation.pending"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
    # User session token TTL (sliding — refreshed on every authenticated
    # request via read_session). 60 min default; NFR-0180 caps mobile at
    # 15 min and USSD at 5 min, so production tenants will dial this DOWN
    # in their `.env`. Local dev / load testing wants headroom.
    SESSION_TTL_SECONDS: int = 60 * 60
    # Short-lived bridge between /otp/verify and /pin/set. Single-use, no
    # sliding window. Sized so a user has plenty of time to type a PIN.
    REGTOKEN_TTL_SECONDS: int = 60 * 60
    # Local-dev only: return the generated OTP in /otp/send response so tests
    # and manual demos can verify without an SMS gateway. MUST be False
    # outside local dev (NFR-0170 — OTPs are credentials and never leave the
    # server in production).
    OTP_DEV_RETURN: bool = True
    LOG_LEVEL: str = "INFO"
    # Local-dev only: opens two routes (`/events/sim-ingest`,
    # `/events/sim-kafka-produce`) so the mobile-simulator app can fire
    # test events without an admin Keycloak token. MUST stay False
    # outside local dev — these routes return 404 when unset.
    SIMULATOR_DEV_MODE: bool = False
    # Celery beat interval (seconds) for segments.recompute_all — the dynamic
    # segment membership refresh (segmentation spec §4). Weekly default.
    #
    # The sweep's per-user balance metric aggregates the tenant's WHOLE ledger
    # with no time bound, so its cost grows with total ledger size rather than
    # with how much changed. Membership in a loyalty/value tier does not move
    # meaningfully within an hour, so paying that scan 168x a week bought
    # freshness nobody consumes. Lower it per-environment if a tenant genuinely
    # needs faster tiering; an admin can always force one via the recompute
    # endpoint.
    SEGMENT_RECOMPUTE_INTERVAL_SECS: int = 604_800
    # Celery beat interval (seconds) for ledger.snapshot_drift_sweep — the
    # cached-balance vs ledger reconciliation. Every 15 minutes.
    #
    # Deliberately NOT the 60s recon cadence: verifying one account costs an
    # aggregate over its whole history, which is the O(rows) work the snapshot
    # exists to keep off the hot path. A bounded batch on a slow beat catches a
    # bad writer within minutes without reintroducing that cost.
    SNAPSHOT_DRIFT_SWEEP_INTERVAL_SECS: int = 900
    # Accounts verified per sweep, newest-touched first.
    SNAPSHOT_DRIFT_BATCH: int = 200


settings = Settings()  # type: ignore[call-arg]
