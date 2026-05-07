from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str
    sync_database_url: str
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    embed_model: str = "nomic-embed-text"
    embed_dimensions: int = 768
    upload_dir: str = "./uploads"
    medlineplus_base_url: str = "https://wsearch.nlm.nih.gov/ws/query"
    medlineplus_connect_url: str = "https://connect.medlineplus.gov/application"
    medlineplus_cache_ttl_days: int = 7

    class Config:
        env_file = ".env"


settings = Settings()
