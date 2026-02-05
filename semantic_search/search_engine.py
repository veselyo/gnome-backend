"""
Unified Search Engine for Gnome
Combines Voyage embeddings + Pinecone search + BM25 reranking

Supports two modes:
1. Proxy mode (default): Uses proxy server - no API keys needed in app
2. Direct mode: Uses direct Voyage/Pinecone APIs - requires API keys
"""

from typing import List, Dict, Any, Optional
import logging
import re
import os

logger = logging.getLogger(__name__)

# Try to import rank_bm25, fall back to simple keyword matching if not available
try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False
    logger.warning("rank_bm25 not installed - using simple keyword matching for reranking")


# ============ Mode Detection ============

def should_use_proxy() -> bool:
    """
    Determine whether to use proxy mode.

    Returns True (proxy mode) if:
    - USE_PROXY env var is set to 'true'
    - OR no local Voyage/Pinecone API keys are configured
    """
    # Explicit setting takes precedence
    use_proxy_env = os.environ.get('USE_PROXY', '').lower()
    if use_proxy_env == 'true':
        return True
    if use_proxy_env == 'false':
        return False

    # Default: use proxy if no local keys configured
    has_voyage_key = bool(os.environ.get('VOYAGE_API_KEY'))
    has_pinecone_key = bool(os.environ.get('PINECONE_API_KEY'))

    return not (has_voyage_key and has_pinecone_key)


class SearchEngine:
    """Unified search engine combining Voyage embeddings and Pinecone vector search."""

    def __init__(self, use_proxy: bool = None):
        """
        Initialize search engine.

        Args:
            use_proxy: Whether to use proxy server. If None, auto-detect.
        """
        self.use_proxy = use_proxy if use_proxy is not None else should_use_proxy()

        if self.use_proxy:
            # Use proxy client
            from .proxy_client import get_proxy_client
            self.proxy = get_proxy_client()
            self.embeddings = None
            self.vector_db = None
            logger.info("SearchEngine initialized in PROXY mode")
        else:
            # Use direct APIs
            from .voyage_embeddings import get_embedding_engine
            from .pinecone_database import get_pinecone_database
            self.proxy = None
            self.embeddings = get_embedding_engine()
            self.vector_db = get_pinecone_database()
            logger.info("SearchEngine initialized in DIRECT mode (local API keys)")

    def index_document(
        self,
        doc_id: str,
        content: str,
        metadata: Dict[str, Any],
        namespace: str = None
    ):
        """
        Index a single document.

        Args:
            doc_id: Unique identifier (typically file_hash)
            content: Text content to embed
            metadata: Metadata dict with filename, source, file_path, etc.
            namespace: Optional namespace for organization
        """
        # Truncate content if too long (voyage-3 has 32K token limit)
        max_chars = 120000
        if len(content) > max_chars:
            content = content[:max_chars]

        # Store content preview in metadata for display
        metadata["content_preview"] = content[:500] if content else ""

        if self.use_proxy:
            embedding = self.proxy.embed_document(content)
            self.proxy.index_document(doc_id, embedding, metadata, namespace)
        else:
            embedding = self.embeddings.embed_document(content)
            self.vector_db.upsert_document(doc_id, embedding, metadata, namespace)

        logger.debug(f"Indexed document: {metadata.get('filename', doc_id)}")

    def index_batch(self, documents: List[Dict[str, Any]], namespace: str = None):
        """
        Index multiple documents efficiently.

        Args:
            documents: List of dicts with keys: id, content, metadata
            namespace: Optional namespace
        """
        if not documents:
            return

        # Prepare texts for embedding
        texts = []
        for doc in documents:
            content = doc.get("content", "")
            max_chars = 120000
            if len(content) > max_chars:
                content = content[:max_chars]
            texts.append(content)
            doc["metadata"]["content_preview"] = content[:500] if content else ""

        if self.use_proxy:
            # Proxy handles embedding + indexing together
            docs_for_proxy = []
            for doc, text in zip(documents, texts):
                docs_for_proxy.append({
                    'id': doc['id'],
                    'content': text,
                    'metadata': doc['metadata']
                })
            self.proxy.index_batch(docs_for_proxy, namespace)
        else:
            # Direct mode: batch embed then upsert
            embeddings = self.embeddings.embed_batch(texts, input_type="document")

            vectors = []
            for doc, embedding in zip(documents, embeddings):
                vectors.append({
                    "id": doc["id"],
                    "embedding": embedding,
                    "metadata": doc["metadata"]
                })

            self.vector_db.upsert_batch(vectors, namespace)

        logger.info(f"Batch indexed {len(documents)} documents")

    def search(
        self,
        query: str,
        top_k: int = 15,
        source_filter: Optional[str] = None,
        use_reranking: bool = True,
        namespace: str = None
    ) -> List[Dict[str, Any]]:
        """
        Search for documents matching the query.

        Args:
            query: Natural language search query
            top_k: Number of results to return
            source_filter: Optional filter by source (e.g., "Gmail", "Finder")
            use_reranking: Whether to apply BM25 reranking
            namespace: Optional namespace to search

        Returns:
            List of search results with score and metadata
        """
        # Validate query
        if not query or not query.strip():
            logger.warning("Empty search query")
            return []

        # Truncate very long queries (Voyage has limits)
        query = query.strip()[:2000]

        # Get query embedding
        if self.use_proxy:
            query_embedding = self.proxy.embed_query(query)
        else:
            query_embedding = self.embeddings.embed_query(query)

        # Handle case where embedding returns None or empty
        if query_embedding is None or len(query_embedding) == 0:
            logger.warning("Failed to generate query embedding")
            return []

        # Convert to list if numpy array (fixes comparison issues)
        if hasattr(query_embedding, 'tolist'):
            query_embedding = query_embedding.tolist()

        # Build filter if source specified
        filter_dict = None
        if source_filter:
            filter_dict = {"source": source_filter}

        # Fetch more results for reranking
        fetch_k = top_k * 3 if use_reranking else top_k

        # Vector search
        if self.use_proxy:
            results = self.proxy.search(
                query_embedding,
                top_k=fetch_k,
                filter_dict=filter_dict,
                namespace=namespace
            )
            # Convert proxy results to expected format
            results = [
                {
                    'id': r['id'],
                    'score': r['score'],
                    'metadata': r.get('metadata', {})
                }
                for r in results
            ]
        else:
            results = self.vector_db.search(
                query_embedding,
                top_k=fetch_k,
                filter=filter_dict,
                namespace=namespace
            )

        if not results:
            return []

        if use_reranking:
            results = self._rerank_results(query, results, top_k)

        return results[:top_k]

    def _rerank_results(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Rerank results using BM25 + semantic score fusion.

        Weights:
        - Semantic similarity: 50%
        - BM25 keyword match: 30%
        - Filename match: 20%
        """
        if not results:
            return results

        # Use consistent tokenization for query
        query_terms = self._tokenize(query)

        # Prepare corpus for BM25
        corpus = []
        for r in results:
            text = r["metadata"].get("content_preview", "") + " " + r["metadata"].get("filename", "")
            tokens = self._tokenize(text)
            corpus.append(tokens)

        # BM25 scoring
        if HAS_BM25 and corpus and any(corpus):
            bm25 = BM25Okapi(corpus)
            bm25_scores = bm25.get_scores(query_terms)

            # Convert numpy array to list to avoid comparison issues
            if hasattr(bm25_scores, 'tolist'):
                bm25_scores = bm25_scores.tolist()

            # Normalize BM25 scores (efficiently)
            max_bm25 = max(bm25_scores) if bm25_scores and len(bm25_scores) > 0 else 0
            if max_bm25 > 0:
                bm25_scores = [s / max_bm25 for s in bm25_scores]
            else:
                bm25_scores = [0] * len(results)
        else:
            # Simple keyword matching fallback
            bm25_scores = []
            for tokens in corpus:
                token_set = set(tokens)
                matches = sum(1 for term in query_terms if term in token_set)
                bm25_scores.append(matches / len(query_terms) if query_terms else 0)

        # Calculate filename match scores
        filename_scores = []
        for r in results:
            filename = r["metadata"].get("filename", "").lower()
            matches = sum(1 for term in query_terms if term in filename)
            filename_scores.append(matches / len(query_terms) if query_terms else 0)

        # Combine scores
        for i, r in enumerate(results):
            semantic_score = r["score"]  # Already 0-1 from cosine similarity
            bm25_score = bm25_scores[i] if i < len(bm25_scores) else 0
            filename_score = filename_scores[i] if i < len(filename_scores) else 0

            r["combined_score"] = (
                0.50 * semantic_score +
                0.30 * bm25_score +
                0.20 * filename_score
            )

        # Sort by combined score
        results.sort(key=lambda x: x.get("combined_score", x["score"]), reverse=True)

        return results

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25."""
        # Lowercase and split on non-alphanumeric
        tokens = re.findall(r'\b\w+\b', text.lower())
        return tokens

    def delete_document(self, doc_id: str, namespace: str = None):
        """Delete a document from the index."""
        if self.use_proxy:
            self.proxy.delete_document(doc_id, namespace)
        else:
            self.vector_db.delete_by_id(doc_id, namespace)

    def delete_source(self, source: str, namespace: str = None):
        """Delete all documents from a source."""
        if self.use_proxy:
            self.proxy.delete_source(source, namespace)
        else:
            self.vector_db.delete_by_source(source, namespace)

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        if self.use_proxy:
            return self.proxy.get_stats()
        else:
            return self.vector_db.get_stats()

    def document_exists(self, doc_id: str, namespace: str = None) -> bool:
        """Check if a document exists in the index."""
        if self.use_proxy:
            # Proxy doesn't have direct exists check, so we search for it
            # For now, return False (document will be re-indexed if it exists)
            return False
        else:
            return self.vector_db.document_exists(doc_id, namespace)


# Singleton instance
_ENGINE = None


def get_search_engine() -> Optional[SearchEngine]:
    """Get or create the singleton search engine. Returns None if not configured."""
    global _ENGINE
    if _ENGINE is None:
        try:
            _ENGINE = SearchEngine()
        except Exception as e:
            logger.error(f"Failed to initialize search engine: {e}")
            return None
    return _ENGINE


def is_configured() -> bool:
    """Check if search is configured (either proxy or direct mode)."""
    if should_use_proxy():
        # Proxy mode - check if proxy is reachable
        try:
            from .proxy_client import is_proxy_configured
            return is_proxy_configured()
        except Exception:
            return False
    else:
        # Direct mode - check if API keys are set
        from .voyage_embeddings import is_configured as voyage_configured
        from .pinecone_database import is_configured as pinecone_configured
        return voyage_configured() and pinecone_configured()
