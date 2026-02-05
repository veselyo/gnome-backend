"""
Pinecone Vector Database for Gnome
Handles all vector storage and similarity search operations
"""

import os
from typing import List, Dict, Any, Optional
from pinecone import Pinecone, ServerlessSpec
import time
import logging

logger = logging.getLogger(__name__)


class PineconeDatabase:
    def __init__(self):
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise ValueError("PINECONE_API_KEY environment variable not set")

        self.pc = Pinecone(api_key=api_key)
        self.index_name = os.getenv("PINECONE_INDEX_NAME", "gnome-mvp")
        self.dimension = 1024  # voyage-3 dimension
        self.namespace_default = "documents"

        self._ensure_index_exists()
        self.index = self.pc.Index(self.index_name)

        logger.info(f"Pinecone database initialized (index: {self.index_name})")

    def _ensure_index_exists(self):
        """Create index if it doesn't exist."""
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]

        if self.index_name not in existing_indexes:
            logger.info(f"Creating Pinecone index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region=os.getenv("PINECONE_ENVIRONMENT", "us-east-1")
                )
            )
            # Wait for index to be ready
            while not self.pc.describe_index(self.index_name).status["ready"]:
                logger.info("Waiting for Pinecone index to be ready...")
                time.sleep(1)
            logger.info("Pinecone index created and ready")

    def upsert_document(
        self,
        doc_id: str,
        embedding: List[float],
        metadata: Dict[str, Any],
        namespace: str = None
    ):
        """
        Insert or update a single document.

        Args:
            doc_id: Unique identifier (use file_hash)
            embedding: 1024-dim vector from Voyage
            metadata: Dict with filename, source, file_path, content_preview, etc.
            namespace: Optional namespace for organizing by source
        """
        namespace = namespace or self.namespace_default

        # Pinecone metadata values must be string, number, boolean, or list of strings
        # Sanitize metadata
        clean_metadata = self._clean_metadata(metadata)

        self.index.upsert(
            vectors=[{
                "id": doc_id,
                "values": embedding,
                "metadata": clean_metadata
            }],
            namespace=namespace
        )

    def upsert_batch(
        self,
        documents: List[Dict[str, Any]],
        namespace: str = None
    ):
        """
        Batch insert/update documents.

        Args:
            documents: List of dicts with keys: id, embedding, metadata
            namespace: Optional namespace
        """
        namespace = namespace or self.namespace_default

        # Pinecone recommends batches of 100
        batch_size = 100
        vectors = []

        for doc in documents:
            clean_metadata = self._clean_metadata(doc.get("metadata", {}))

            vectors.append({
                "id": doc["id"],
                "values": doc["embedding"],
                "metadata": clean_metadata
            })

        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self.index.upsert(vectors=batch, namespace=namespace)
            logger.debug(f"Upserted batch of {len(batch)} vectors")

    def _clean_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Clean metadata for Pinecone compatibility."""
        clean_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                # Truncate long strings (Pinecone has limits)
                if isinstance(value, str) and len(value) > 1000:
                    clean_metadata[key] = value[:1000]
                else:
                    clean_metadata[key] = value
            elif isinstance(value, list):
                clean_metadata[key] = [str(v)[:100] for v in value[:10]]  # Limit list size
            elif value is not None:
                clean_metadata[key] = str(value)[:1000]
        return clean_metadata

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 20,
        filter: Dict[str, Any] = None,
        namespace: str = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents.

        Args:
            query_embedding: 1024-dim query vector
            top_k: Number of results to return
            filter: Optional metadata filter (e.g., {"source": "Gmail"})
            namespace: Optional namespace to search in

        Returns:
            List of matches with id, score, and metadata
        """
        namespace = namespace or self.namespace_default

        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
            filter=filter,
            namespace=namespace
        )

        return [
            {
                "id": match.id,
                "score": match.score,
                "metadata": match.metadata or {}
            }
            for match in results.matches
        ]

    def delete_by_id(self, doc_id: str, namespace: str = None):
        """Delete a single document by ID."""
        namespace = namespace or self.namespace_default
        self.index.delete(ids=[doc_id], namespace=namespace)

    def delete_by_ids(self, doc_ids: List[str], namespace: str = None):
        """Delete multiple documents by IDs."""
        namespace = namespace or self.namespace_default
        # Delete in batches of 100
        for i in range(0, len(doc_ids), 100):
            batch = doc_ids[i:i + 100]
            self.index.delete(ids=batch, namespace=namespace)

    def delete_by_source(self, source: str, namespace: str = None):
        """Delete all documents from a specific source."""
        namespace = namespace or self.namespace_default
        # Pinecone requires iterating through and deleting
        # For large deletions, delete by metadata filter
        self.index.delete(
            filter={"source": source},
            namespace=namespace
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return self.index.describe_index_stats()

    def document_exists(self, doc_id: str, namespace: str = None) -> bool:
        """Check if a document ID exists in the index."""
        namespace = namespace or self.namespace_default
        try:
            result = self.index.fetch(ids=[doc_id], namespace=namespace)
            return doc_id in result.vectors
        except Exception:
            return False


# Singleton instance
_DB = None


def get_pinecone_database() -> Optional[PineconeDatabase]:
    """Get or create the singleton Pinecone database. Returns None if API key not set."""
    global _DB
    if _DB is None:
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            logger.warning("PINECONE_API_KEY not set - vector database unavailable")
            return None
        _DB = PineconeDatabase()
    return _DB


def is_configured() -> bool:
    """Check if Pinecone is configured."""
    return os.getenv("PINECONE_API_KEY") is not None
