import httpx
from config import settings

class Embedder:
    def __init__(self):
        self.base_url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
        self.model = settings.EMBEDDING_MODEL

    async def get_embedding(self, text: str) -> list[float]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={"model": self.model, "prompt": text},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()["embedding"]

embedder = Embedder()
