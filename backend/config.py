from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str
    sync_database_url: str
    ollama_base_url: str = "http://localhost:11434"
    # Chosen with the answer eval on 2026-10-19 (docs/adr/0010): English pass
    # rate 92%, median reply 23 s on a CPU-only laptop.
    ollama_model: str = "qwen2.5:3b"
    # Context window of the chat model, sent as Ollama's num_ctx (Ollama's
    # default was 4096). The system prompt alone is ~2.3-3k tokens (measured
    # 2026-10-19) and 512 are reserved for the reply, so 4096 left room for
    # only 1-2 earlier turns. 8192 fits several; the cost is a larger KV cache
    # (qwen2.5:3b takes 2.4 GB loaded with this window) and slower prompt
    # processing on CPU.
    llm_num_ctx: int = 8192
    embed_model: str = "nomic-embed-text"
    embed_dimensions: int = 768
    upload_dir: str = "./uploads"
    medlineplus_base_url: str = "https://wsearch.nlm.nih.gov/ws/query"
    # The Connect *web service* (XML/JSON). The ".../application" URL is the
    # browser-facing web application, which answers with an HTML page.
    medlineplus_connect_url: str = "https://connect.medlineplus.gov/service"
    medlineplus_cache_ttl_days: int = 7
    # RAG operating point, chosen with `python -m eval.retrieval_eval` on 20 HU/EN
    # questions + 5 off-topic ones (2026-10-17, nomic-embed-text with task
    # prefixes, 42 stored records): top-1 at >= 0.62 gave recall 85% (HU 70%,
    # EN 100%) at 85% precision with no off-topic hits. More results raised
    # recall to at most 90% but dropped precision to 32-50%, which distracts a
    # small chat model. Re-run the eval after changing the embedding model,
    # templates or data.
    rag_similarity_threshold: float = 0.62
    rag_top_k: int = 1
    # Age after which a stored risk input is shown as "stale" on the risk form.
    # Stale values stay usable; the user decides whether to enter a fresh one.
    # Practical defaults, not clinical guidance: weight, waist and blood
    # pressure can change within months; a lipid panel is typically repeated
    # about yearly.
    risk_measurement_stale_days: int = 90
    risk_lab_stale_days: int = 365

    class Config:
        env_file = ".env"


settings = Settings()
