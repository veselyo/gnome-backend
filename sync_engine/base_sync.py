"""
Base sync engine class that all sync sources inherit from.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseSyncEngine(ABC):
    """Abstract base class for all sync engines."""
    
    def __init__(self, database, source_name: str):
        """
        Initialize sync engine.
        
        Args:
            database: GnomeDatabase instance
            source_name: Name of the source ('Finder', 'Google Drive', 'OneDrive')
        """
        self.db = database
        self.source_name = source_name
        self.logger = logging.getLogger(f"{__name__}.{source_name}")
    
    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the service.
        
        Returns:
            True if authentication successful, False otherwise
        """
        pass
    
    @abstractmethod
    def fetch_files(self) -> List[Dict]:
        """
        Fetch list of files from the source.
        
        Returns:
            List of file dictionaries with keys:
                - filename: str
                - file_path: str (or cloud ID)
                - file_size: int
                - last_modified: datetime
                - download_url: str (for cloud services)
        """
        pass
    
    @abstractmethod
    def download_file(self, file_info: Dict) -> Optional[Path]:
        """
        Download a file (for cloud services) or return path (for local).
        
        Args:
            file_info: File information dict from fetch_files()
        
        Returns:
            Path to local file, or None if download failed
        """
        pass
    
    def sync(self, voyage_client, pinecone_idx, namespace: str):
        """
        Main sync method - fetches files and indexes new ones.
        
        Args:
            voyage_client: Voyage AI client for embeddings
            pinecone_idx: Pinecone index for storage
            namespace: User's Pinecone namespace
        """
        try:
            self.logger.info(f"Starting sync for {self.source_name}")
            self.db.update_sync_state(self.source_name, 'syncing')
            
            # Fetch files from source
            files = self.fetch_files()
            self.logger.info(f"Found {len(files)} files in {self.source_name}")
            
            indexed_count = 0
            skipped_count = 0
            
            for file_info in files:
                try:
                    # Check if already indexed
                    file_hash = file_info.get('file_hash')
                    if self.db.get_file_by_hash(file_hash):
                        skipped_count += 1
                        continue
                    
                    # Download/get local path
                    local_path = self.download_file(file_info)
                    if not local_path:
                        self.logger.warning(f"Failed to download: {file_info['filename']}")
                        continue
                    
                    # Index the file
                    if self.index_file(local_path, file_info, voyage_client, 
                                      pinecone_idx, namespace):
                        indexed_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Error processing {file_info.get('filename')}: {e}")
                    continue
            
            self.db.update_sync_state(self.source_name, 'idle')
            self.logger.info(f"Sync complete: {indexed_count} indexed, {skipped_count} skipped")
            
            return {
                'indexed': indexed_count,
                'skipped': skipped_count,
                'total': len(files)
            }
            
        except Exception as e:
            self.logger.error(f"Sync failed for {self.source_name}: {e}")
            self.db.update_sync_state(self.source_name, 'error', error=str(e))
            raise
    
    def index_file(self, file_path: Path, file_info: Dict, voyage_client, 
                   pinecone_idx, namespace: str) -> bool:
        """
        Index a single file.
        
        Args:
            file_path: Local path to the file
            file_info: File metadata dict
            voyage_client: Voyage AI client
            pinecone_idx: Pinecone index
            namespace: User's namespace
        
        Returns:
            True if indexed successfully, False otherwise
        """
        try:
            from semantic_search.parsing_engine import parse_local_pdf
            from semantic_search.embedding_engine import embed_pdf
            from semantic_search.vector_database import store_embeddings
            from database.models import compute_file_hash
            
            # Only process PDFs for now
            if not str(file_path).lower().endswith('.pdf'):
                return False
            
            # Parse PDF to images
            images = parse_local_pdf(str(file_path))
            
            # Generate embeddings
            embedding = embed_pdf(images, voyage_client)
            
            # Create unique Pinecone ID
            pinecone_id = f"{self.source_name}_{file_info['filename']}"
            
            # Store in Pinecone
            store_embeddings(pinecone_id, pinecone_idx, embedding, namespace)
            
            # Compute file hash
            file_hash = compute_file_hash(str(file_path))
            
            # Save to database
            self.db.add_file(
                filename=file_info['filename'],
                file_path=file_info.get('file_path', str(file_path)),
                source=self.source_name,
                file_hash=file_hash,
                pinecone_id=pinecone_id,
                file_size=file_info.get('file_size'),
                metadata=file_info.get('metadata')
            )
            
            self.logger.info(f"Indexed: {file_info['filename']}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to index {file_info['filename']}: {e}")
            return False
    
    def is_authenticated(self) -> bool:
        """
        Check if service is authenticated.
        
        Returns:
            True if authenticated, False otherwise
        """
        # Override in subclasses that need OAuth
        return True

