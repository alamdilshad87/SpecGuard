from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPECGUARD_")

    app_name: str = "SpecGuard"
    database_url: str = "postgresql+psycopg2://specguard:specguard@localhost:5432/specguard"
    cors_origins: list[str] = ["http://localhost:5173"]
    # Upper bound for requests the test runner sends to a target API
    runner_timeout_seconds: float = 10.0

    # Optional LLM for the /ask endpoint: any OpenAI-compatible chat completions API.
    # Leave base URL or model empty to use extractive (offline) answers.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0


settings = Settings()
