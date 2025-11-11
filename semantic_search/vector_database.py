"""
Local vector database using ChromaDB.
100% private - all vectors stored locally in ~/.gnome/chroma/
No cloud services, no data leaves your Mac.
"""
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Optional
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Global ChromaDB client and collection
_CHROMA_CLIENT = None
_COLLECTION = None


def init_chroma_db(namespace: str = "default"):
    """
    Initialize local ChromaDB persistent storage.
    
    Args:
        namespace: User-specific namespace (e.g., "user_abc123" or "demo")
    
    Returns:
        ChromaDB collection instance
    """
    global _CHROMA_CLIENT, _COLLECTION
    
    if _COLLECTION is not None:
        return _COLLECTION
    
    try:
        # Determine storage path
        chroma_path = Path.home() / '.gnome' / 'chroma' / namespace
        chroma_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📁 Initializing local vector database at: {chroma_path}")
        
        # Create persistent ChromaDB client (no telemetry)
        _CHROMA_CLIENT = chromadb.PersistentClient(
            path=str(chroma_path),
            settings=Settings(
                anonymized_telemetry=False,  # Privacy: No telemetry!
                allow_reset=True
            )
        )
        
        # Get or create collection
        _COLLECTION = _CHROMA_CLIENT.get_or_create_collection(
            name="gnome_files",
            metadata={
                "hnsw:space": "cosine",  # Cosine similarity for normalized vectors
                "hnsw:M": 16,            # HNSW index parameter (tradeoff: speed vs accuracy)
                "description": "Gnome local file search - 100% private"
            }
        )
        
        # Get stats
        count = _COLLECTION.count()
        logger.info(f"✅ Local vector database initialized")
        logger.info(f"   Storage: {chroma_path}")
        logger.info(f"   Collection: gnome_files")
        logger.info(f"   Vectors: {count:,}")
        logger.info(f"   Privacy: 100% LOCAL - No cloud sync!")
        
        return _COLLECTION
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize ChromaDB: {e}")
        raise


def init_pinecone_idx():
    """Legacy function - now uses ChromaDB instead of Pinecone."""
    logger.warning("init_pinecone_idx() called - using ChromaDB instead")
    return init_chroma_db()


def store_embeddings(filename: str, collection, embedding: List[float], namespace: str = "default", metadata: Dict = None):
    """
    Store document embedding in local ChromaDB.
    
    Args:
        filename: Name of the file
        collection: ChromaDB collection (ignored, uses global)
        embedding: 1024-dimensional vector
        namespace: User namespace (for isolation)
        metadata: Additional metadata (source, file_path, etc.)
    """
    try:
        # Initialize if needed
        if _COLLECTION is None:
            init_chroma_db(namespace)
        
        # Create unique ID
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        doc_id = f"{namespace}_{filename}_{timestamp}"
        
        # Prepare metadata
        meta = metadata or {}
        meta.update({
            'filename': filename,
            'namespace': namespace,
            'indexed_at': timestamp
        })
        
        # Store in ChromaDB
        _COLLECTION.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[filename],  # Store filename as document for full-text search
            metadatas=[meta]
        )
        
        logger.debug(f"✅ Stored: {filename} (ID: {doc_id})")
        
    except Exception as e:
        logger.error(f"Failed to store embedding for {filename}: {e}")
        raise


def semantic_search(query: str, collection, voyage_client, top_k: int = 100, namespace: str = "default") -> Dict:
    """
    Perform semantic search using local ChromaDB.
    
    Args:
        query: Search query text
        collection: Ignored (uses global ChromaDB collection)
        voyage_client: Local embedder client
        top_k: Number of results to return
        namespace: User namespace for filtering
    
    Returns:
        Dict with 'matches' list (Pinecone-compatible format)
    """
    try:
        # Initialize if needed
        if _COLLECTION is None:
            init_chroma_db(namespace)
        
        # Generate query embedding using local model
        query_embedding = voyage_client.embed([query], input_type="query").embeddings[0]
        
        # Search ChromaDB
        results = _COLLECTION.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"namespace": namespace} if namespace != "default" else None,
            include=['distances', 'documents', 'metadatas']
        )
        
        # Convert to Pinecone-compatible format
        matches = []
        if results and results['ids'] and len(results['ids']) > 0:
            ids = results['ids'][0]
            distances = results['distances'][0]
            documents = results['documents'][0]
            metadatas = results['metadatas'][0]
            
            for i, doc_id in enumerate(ids):
                # ChromaDB returns distances (lower = better)
                # Convert to similarity score (higher = better)
                # Distance is L2 for cosine space, convert to similarity
                similarity = 1 - (distances[i] / 2)  # Normalize to 0-1
                
                matches.append({
                    'id': doc_id,
                    'score': max(0, min(1, similarity)),  # Clamp to [0, 1]
                    'metadata': metadatas[i] if metadatas else {}
                })
        
        logger.debug(f"🔍 Search '{query}': {len(matches)} results from local DB")
        
        return {'matches': matches}
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {'matches': []}


def delete_embeddings(doc_ids: List[str]):
    """
    Delete embeddings from ChromaDB.
    
    Args:
        doc_ids: List of document IDs to delete
    """
    try:
        if _COLLECTION is None:
            logger.warning("Collection not initialized, cannot delete")
            return
        
        _COLLECTION.delete(ids=doc_ids)
        logger.info(f"🗑️  Deleted {len(doc_ids)} embeddings")
        
    except Exception as e:
        logger.error(f"Failed to delete embeddings: {e}")


def get_collection_stats() -> Dict:
    """Get statistics about the local vector database."""
    try:
        if _COLLECTION is None:
            return {'count': 0, 'status': 'not_initialized'}
        
        count = _COLLECTION.count()
        return {
            'count': count,
            'status': 'ready',
            'storage': 'local',
            'privacy': '100% private'
        }
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return {'count': 0, 'status': 'error', 'error': str(e)}
