"""
Voyage AI Embedding Engine for Gnome
Uses voyage-3 model (1024 dimensions, 32K context)
"""

import os
import voyageai
from typing import List, Optional
import hashlib
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class VoyageEmbeddingEngine:
    def __init__(self):
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            raise ValueError("VOYAGE_API_KEY environment variable not set")

        self.client = voyageai.Client(api_key=api_key)
        self.model = "voyage-3"  # 1024 dimensions, best quality
        self.dimension = 1024
        self.max_tokens = 32000
        self.batch_size = 128  # Voyage allows up to 128 texts per batch

        # Local cache to avoid re-embedding identical content
        self.cache_dir = Path.home() / ".gnome" / "embedding_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Voyage AI client initialized (model: {self.model})")

    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text content."""
        return hashlib.sha256(text.encode()).hexdigest()

    def _get_cached_embedding(self, cache_key: str) -> Optional[List[float]]:
        """Retrieve embedding from local cache if exists."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def _cache_embedding(self, cache_key: str, embedding: List[float]):
        """Store embedding in local cache."""
        cache_file = self.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_file, "w") as f:
                json.dump(embedding, f)
        except Exception as e:
            logger.warning(f"Failed to cache embedding: {e}")

    def embed_text(self, text: str, input_type: str = "document") -> Optional[List[float]]:
        """
        Embed a single text string.

        Args:
            text: The text to embed
            input_type: "document" for indexing, "query" for searching

        Returns:
            1024-dimensional embedding vector, or None if text is empty
        """
        # Validate input
        if not text or not text.strip():
            logger.warning("Cannot embed empty text")
            return None

        text = text.strip()

        cache_key = self._get_cache_key(text + input_type)
        cached = self._get_cached_embedding(cache_key)
        if cached:
            return cached

        # Truncate if too long (rough estimate: 4 chars per token)
        max_chars = self.max_tokens * 4
        if len(text) > max_chars:
            text = text[:max_chars]
            logger.warning(f"Text truncated to {max_chars} characters")

        result = self.client.embed(
            texts=[text],
            model=self.model,
            input_type=input_type
        )
        embedding = result.embeddings[0]
        self._cache_embedding(cache_key, embedding)
        return embedding

    def embed_batch(self, texts: List[str], input_type: str = "document") -> List[List[float]]:
        """
        Embed multiple texts efficiently.

        Args:
            texts: List of texts to embed
            input_type: "document" for indexing, "query" for searching

        Returns:
            List of 1024-dimensional embedding vectors
        """
        embeddings = []
        uncached_texts = []
        uncached_indices = []

        # Check cache first
        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text + input_type)
            cached = self._get_cached_embedding(cache_key)
            if cached:
                embeddings.append((i, cached))
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        # Batch embed uncached texts
        if uncached_texts:
            # Truncate texts if needed
            max_chars = self.max_tokens * 4
            truncated_texts = []
            for text in uncached_texts:
                if len(text) > max_chars:
                    truncated_texts.append(text[:max_chars])
                else:
                    truncated_texts.append(text)

            for batch_start in range(0, len(truncated_texts), self.batch_size):
                batch_end = min(batch_start + self.batch_size, len(truncated_texts))
                batch_texts = truncated_texts[batch_start:batch_end]
                batch_indices = uncached_indices[batch_start:batch_end]
                original_texts = uncached_texts[batch_start:batch_end]

                try:
                    result = self.client.embed(
                        texts=batch_texts,
                        model=self.model,
                        input_type=input_type
                    )

                    for idx, embedding, text in zip(batch_indices, result.embeddings, original_texts):
                        cache_key = self._get_cache_key(text + input_type)
                        self._cache_embedding(cache_key, embedding)
                        embeddings.append((idx, embedding))

                except Exception as e:
                    logger.error(f"Batch embedding failed: {e}")
                    raise

        # Sort by original index and return just embeddings
        embeddings.sort(key=lambda x: x[0])
        return [e[1] for e in embeddings]

    def embed_query(self, query: str) -> List[float]:
        """Embed a search query (uses query-optimized embedding)."""
        return self.embed_text(query, input_type="query")

    def embed_document(self, text: str) -> List[float]:
        """Embed a document for indexing."""
        return self.embed_text(text, input_type="document")


# Singleton instance
_ENGINE = None


def get_embedding_engine() -> Optional[VoyageEmbeddingEngine]:
    """Get or create the singleton embedding engine. Returns None if API key not set."""
    global _ENGINE
    if _ENGINE is None:
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            logger.warning("VOYAGE_API_KEY not set - embedding engine unavailable")
            return None
        _ENGINE = VoyageEmbeddingEngine()
    return _ENGINE


def is_configured() -> bool:
    """Check if Voyage AI is configured."""
    return os.getenv("VOYAGE_API_KEY") is not None
