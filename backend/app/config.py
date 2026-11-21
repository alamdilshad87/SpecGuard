from typing import Literal

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

    # Optional .NET Roslyn scanner (scanner-dotnet/) used for .cs files in drift scans.
    csharp_scanner_url: str = ""
    csharp_scanner_timeout_seconds: float = 30.0

    # Embeddings for semantic retrieval in /ask. "fastembed" runs a local ONNX model;
    # "none" disables vector search (keyword-only BM25).
    embedding_provider: Literal["fastembed", "none"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ""  # default: fastembed's own cache location


settings = Settings()
