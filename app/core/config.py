from dataclasses import dataclass
import os

_INSECURE_JWT_SECRET = "change-me-in-production"


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./headway.db")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", _INSECURE_JWT_SECRET)
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
    auto_create_tables: bool = os.getenv("AUTO_CREATE_TABLES", "false").lower() == "true"
    environment: str = os.getenv("ENVIRONMENT", "development")

    def __post_init__(self) -> None:
        # Refuse to start in production with the placeholder signing key, which
        # would let anyone forge valid JWTs.
        if self.environment == "production" and self.jwt_secret_key == _INSECURE_JWT_SECRET:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to a strong secret when ENVIRONMENT=production"
            )


settings = Settings()
