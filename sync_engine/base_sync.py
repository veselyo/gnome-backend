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
    
    def sync(self, voyage_client, pinecone_idx, namespace: str, max_files: int = None):
        """
        Main sync method - fetches files and indexes new ones.
        
        Args:
            voyage_client: Voyage AI client for embeddings
            pinecone_idx: Pinecone index for storage
            namespace: User's Pinecone namespace
            max_files: Max files to index in one sync (None = all)
        """
        try:
            self.logger.info(f"🔄 Starting sync for {self.source_name}")
            self.db.update_sync_state(self.source_name, 'syncing')
            
            # Fetch files from source
            files = self.fetch_files()
            self.logger.info(f"📁 Found {len(files)} files in {self.source_name}")
            
            indexed_count = 0
            skipped_count = 0
            error_count = 0
            
            # Limit files per sync for faster iterations
            if max_files:
                files = files[:max_files]
            
            for i, file_info in enumerate(files):
                try:
                    # Check if already indexed
                    file_hash = file_info.get('file_hash')
                    if file_hash and self.db.get_file_by_hash(file_hash):
                        skipped_count += 1
                        continue
                    
                    # Download/get local path
                    local_path = self.download_file(file_info)
                    if not local_path:
                        self.logger.warning(f"Failed to download: {file_info['filename']}")
                        error_count += 1
                        continue
                    
                    # Index the file
                    if self.index_file(local_path, file_info, voyage_client, 
                                      pinecone_idx, namespace):
                        indexed_count += 1
                        if (indexed_count % 10 == 0):
                            self.logger.info(f"Progress: {indexed_count}/{len(files)} indexed")
                    else:
                        error_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Error processing {file_info.get('filename')}: {e}")
                    error_count += 1
                    continue
            
            self.db.update_sync_state(self.source_name, 'idle')
            self.logger.info(f"✅ Sync complete: {indexed_count} indexed, {skipped_count} skipped, {error_count} errors")
            
            return {
                'indexed': indexed_count,
                'skipped': skipped_count,
                'errors': error_count,
                'total': len(files)
            }
            
        except Exception as e:
            self.logger.error(f"❌ Sync failed for {self.source_name}: {e}")
            self.db.update_sync_state(self.source_name, 'error', error=str(e))
            raise
    
    def index_file(self, file_path: Path, file_info: Dict, voyage_client, 
                   pinecone_idx, namespace: str) -> bool:
        """
        Index a single file using multi-format processor.
        
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
            from semantic_search.file_processor import process_file, is_supported_file
            from semantic_search.vector_database import store_embeddings
            from database.models import compute_file_hash
            
            # Check if file type is supported
            if not is_supported_file(file_path):
                self.logger.debug(f"Skipping unsupported file type: {file_path}")
                return False
            
            # Process file and get embeddings (works for all formats)
            embedding = process_file(str(file_path), voyage_client)
            
            # Create unique Pinecone ID (ASCII only, replace special chars)
            import re
            import hashlib
            
            # Sanitize filename to ASCII
            safe_filename = file_info['filename'].encode('ascii', 'ignore').decode('ascii')
            safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', safe_filename)
            
            # Create short hash for uniqueness
            file_hash_short = hashlib.md5(file_info['filename'].encode()).hexdigest()[:8]
            
            # Combine: source_hash_filename (all ASCII safe)
            pinecone_id = f"{self.source_name.replace(' ', '_')}_{file_hash_short}_{safe_filename[:100]}"
            
            # Store in Pinecone with metadata
            metadata_to_store = {
                'source': self.source_name,
                'filename': file_info['filename'],
                'file_path': file_info.get('file_path', str(file_path))
            }
            if file_info.get('metadata'):
                metadata_to_store.update(file_info['metadata'])
            
            pinecone_idx.upsert(
                vectors=[{
                    "id": pinecone_id,
                    "values": embedding,
                    "metadata": metadata_to_store
                }],
                namespace=namespace
            )
            
            # Compute file hash if not provided
            file_hash = file_info.get('file_hash')
            if not file_hash:
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
            
            self.logger.info(f"✅ Indexed: {file_info['filename']}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to index {file_info['filename']}: {e}")
            return False
    
    def is_authenticated(self) -> bool:
        """
        Check if service is authenticated.
        
        Returns:
            True if authenticated, False otherwise
        """
        # Override in subclasses that need OAuth
        return True

