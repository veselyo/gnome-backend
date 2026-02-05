"""
Proxy Client for Gnome App

This client calls the Gnome Proxy Server instead of Voyage AI and Pinecone directly.
This keeps your API keys secure on the server.
No authentication required - the proxy server is open for embedding/search.
"""

import requests
import logging
import hashlib
import platform
import os
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ============ Configuration ============
# Proxy server URL - the only config needed
PROXY_URL = os.environ.get('PROXY_URL', 'https://gnome-production.up.railway.app')


def get_namespace() -> str:
    """
    Generate a unique namespace for this user/machine.
    Each user gets their own isolated space in Pinecone.
    """
    try:
        # Create unique ID from machine info
        machine_id = platform.node()  # hostname
        user = os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))
        unique_str = f"{machine_id}:{user}"
        namespace = f"user_{hashlib.sha256(unique_str.encode()).hexdigest()[:16]}"
        return namespace
    except Exception:
        return "user_default"


class ProxyClient:
    """Client for calling the Gnome Proxy Server."""

    def __init__(self, proxy_url: str = None):
        self.base_url = (proxy_url or PROXY_URL).rstrip('/')
        self.headers = {
            'Content-Type': 'application/json'
        }
        self.namespace = get_namespace()
        self.timeout = 60  # seconds

        logger.info(f"ProxyClient initialized: {self.base_url}")
        logger.info(f"User namespace: {self.namespace}")

    def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make a request to the proxy server."""
        url = f"{self.base_url}{endpoint}"

        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, timeout=self.timeout)
            else:
                response = requests.post(url, json=data, headers=self.headers, timeout=self.timeout)

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"Timeout calling {endpoint}")
            raise Exception("Proxy server timeout - please try again")

        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error calling {endpoint}")
            raise Exception("Cannot connect to proxy server - check your internet connection")

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {response.status_code}: {response.text}")
            if response.status_code == 401:
                raise Exception("Unauthorized - invalid app secret")
            raise Exception(f"Proxy server error: {response.text}")

        except Exception as e:
            logger.error(f"Error calling proxy: {e}")
            raise

    # ============ Embedding Operations ============

    def embed(self, texts: List[str], input_type: str = 'document') -> List[List[float]]:
        """
        Generate embeddings for texts.

        Args:
            texts: List of strings to embed
            input_type: 'document' or 'query'

        Returns:
            List of embedding vectors (1024 dimensions each)
        """
        if not texts:
            return []

        result = self._request('POST', '/api/embed', {
            'texts': texts,
            'input_type': input_type
        })

        return result.get('embeddings', [])

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query."""
        embeddings = self.embed([query], input_type='query')
        return embeddings[0] if embeddings else []

    def embed_document(self, text: str) -> List[float]:
        """Embed a single document."""
        embeddings = self.embed([text], input_type='document')
        return embeddings[0] if embeddings else []

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple documents."""
        return self.embed(texts, input_type='document')

    # ============ Vector Search Operations ============

    def search(
        self,
        embedding: List[float],
        top_k: int = 20,
        filter_dict: Dict = None,
        namespace: str = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar vectors.

        Args:
            embedding: Query embedding vector
            top_k: Number of results to return
            filter_dict: Optional metadata filter
            namespace: Optional namespace (uses user namespace by default)

        Returns:
            List of matches with id, score, and metadata
        """
        result = self._request('POST', '/api/search', {
            'embedding': embedding,
            'namespace': namespace or self.namespace,
            'top_k': top_k,
            'filter': filter_dict
        })

        return result.get('matches', [])

    # ============ Index Operations ============

    def index_document(
        self,
        doc_id: str,
        embedding: List[float],
        metadata: Dict[str, Any],
        namespace: str = None
    ) -> bool:
        """
        Index a single document.

        Args:
            doc_id: Unique document ID
            embedding: Document embedding vector
            metadata: Document metadata
            namespace: Optional namespace

        Returns:
            True if successful
        """
        vectors = [{
            'id': doc_id,
            'values': embedding,
            'metadata': metadata
        }]

        result = self._request('POST', '/api/index', {
            'vectors': vectors,
            'namespace': namespace or self.namespace
        })

        return result.get('success', False)

    def index_batch(
        self,
        documents: List[Dict[str, Any]],
        namespace: str = None
    ) -> bool:
        """
        Index multiple documents.

        Args:
            documents: List of {id, content, metadata} dicts
            namespace: Optional namespace

        Returns:
            True if successful
        """
        if not documents:
            return True

        # First, generate embeddings for all documents
        texts = [doc['content'] for doc in documents]
        embeddings = self.embed_batch(texts)

        if len(embeddings) != len(documents):
            logger.error(f"Embedding count mismatch: {len(embeddings)} vs {len(documents)}")
            return False

        # Prepare vectors for Pinecone
        vectors = []
        for i, doc in enumerate(documents):
            vectors.append({
                'id': doc['id'],
                'values': embeddings[i],
                'metadata': doc.get('metadata', {})
            })

        # Index the vectors
        result = self._request('POST', '/api/index', {
            'vectors': vectors,
            'namespace': namespace or self.namespace
        })

        return result.get('success', False)

    # ============ Delete Operations ============

    def delete_document(self, doc_id: str, namespace: str = None) -> bool:
        """Delete a single document by ID."""
        result = self._request('POST', '/api/delete', {
            'ids': [doc_id],
            'namespace': namespace or self.namespace
        })
        return result.get('success', False)

    def delete_by_ids(self, doc_ids: List[str], namespace: str = None) -> bool:
        """Delete multiple documents by ID."""
        result = self._request('POST', '/api/delete', {
            'ids': doc_ids,
            'namespace': namespace or self.namespace
        })
        return result.get('success', False)

    def delete_source(self, source: str, namespace: str = None) -> bool:
        """Delete all documents from a source."""
        result = self._request('POST', '/api/delete', {
            'filter': {'source': source},
            'namespace': namespace or self.namespace
        })
        return result.get('success', False)

    def delete_all(self, namespace: str = None) -> bool:
        """Delete all documents in the namespace."""
        result = self._request('POST', '/api/delete', {
            'delete_all': True,
            'namespace': namespace or self.namespace
        })
        return result.get('success', False)

    # ============ Stats ============

    def get_stats(self, namespace: str = None) -> Dict[str, Any]:
        """Get index statistics."""
        result = self._request('POST', '/api/stats', {
            'namespace': namespace or self.namespace
        })
        return result

    # ============ Health Check ============

    def health_check(self) -> bool:
        """Check if proxy server is healthy."""
        try:
            result = self._request('GET', '/health')
            return result.get('status') == 'ok'
        except Exception:
            return False


# ============ Singleton Instance ============

_proxy_client = None

def get_proxy_client() -> ProxyClient:
    """Get or create the singleton proxy client."""
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = ProxyClient()
    return _proxy_client


def is_proxy_configured() -> bool:
    """Check if proxy is configured and reachable."""
    try:
        client = get_proxy_client()
        return client.health_check()
    except Exception:
        return False
