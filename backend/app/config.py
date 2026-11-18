from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPECGUARD_")

    app_name: str = "SpecGuard"
    database_url: str = "postgresql+psycopg2://specguard:specguard@localhost:5432/specguard"
    cors_origins: list[str] = ["http://localhost:5173"]
    # Upper bound for requests the test runner sends to a target API
    runner_timeout_seconds: float = 10.0


settings = Settings()
