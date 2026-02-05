"""
Base sync engine class that all sync sources inherit from.
Uses new SearchEngine for Voyage AI + Pinecone.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from pathlib import Path
import logging
import hashlib

from semantic_search.search_engine import SearchEngine, get_search_engine
from semantic_search.file_processor import extract_text, is_supported_file
from database.models import (
    GnomeDatabase, compute_file_hash, upsert_file,
    get_file_by_hash, update_sync_state
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaseSyncEngine(ABC):
    """Abstract base class for all sync engines."""

    def __init__(self, database: GnomeDatabase, source_name: str):
        """
        Initialize sync engine.

        Args:
            database: GnomeDatabase instance
            source_name: Name of the source ('Finder', 'Google Drive', 'Gmail', etc.)
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
                - file_hash: str (optional, computed if not provided)
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

    def sync(self, search_engine: SearchEngine = None, max_files: int = None) -> Dict[str, int]:
        """
        Main sync method - fetches files and indexes new ones.

        Args:
            search_engine: SearchEngine instance (uses singleton if not provided)
            max_files: Max files to index in one sync (None = all)

        Returns:
            Dict with sync statistics
        """
        if search_engine is None:
            search_engine = get_search_engine()

        try:
            self.logger.info(f"Starting sync for {self.source_name}")
            update_sync_state(self.source_name, 'syncing')

            # Clean up deleted files first (for local sources)
            self.cleanup_deleted_files(search_engine)

            # Fetch files from source
            files = self.fetch_files()
            self.logger.info(f"Found {len(files)} files in {self.source_name}")

            indexed_count = 0
            skipped_count = 0
            error_count = 0

            # Limit files per sync for faster iterations
            if max_files:
                files = files[:max_files]

            for i, file_info in enumerate(files):
                try:
                    # Check if already indexed (by hash)
                    file_hash = file_info.get('file_hash')
                    if file_hash and get_file_by_hash(file_hash):
                        skipped_count += 1
                        continue

                    # Download/get local path
                    local_path = self.download_file(file_info)
                    if not local_path:
                        self.logger.warning(f"Failed to download: {file_info['filename']}")
                        error_count += 1
                        continue

                    # Index the file
                    if self.index_file(local_path, file_info, search_engine):
                        indexed_count += 1
                        if indexed_count % 10 == 0:
                            self.logger.info(f"Progress: {indexed_count}/{len(files)} indexed")
                    else:
                        error_count += 1

                except Exception as e:
                    self.logger.error(f"Error processing {file_info.get('filename')}: {e}")
                    error_count += 1
                    continue

            update_sync_state(self.source_name, 'idle')
            self.logger.info(f"Sync complete: {indexed_count} indexed, {skipped_count} skipped, {error_count} errors")

            return {
                'indexed': indexed_count,
                'skipped': skipped_count,
                'errors': error_count,
                'total': len(files)
            }

        except Exception as e:
            self.logger.error(f"Sync failed for {self.source_name}: {e}")
            update_sync_state(self.source_name, 'error', error_message=str(e))
            raise

    def index_file(
        self,
        file_path: Path,
        file_info: Dict,
        search_engine: SearchEngine
    ) -> bool:
        """
        Index a single file using the SearchEngine.

        Args:
            file_path: Local path to the file
            file_info: File metadata dict
            search_engine: SearchEngine instance

        Returns:
            True if indexed successfully, False otherwise
        """
        try:
            # Check if file type is supported
            if not is_supported_file(file_path):
                self.logger.debug(f"Skipping unsupported file type: {file_path}")
                return False

            # Extract text content
            content = extract_text(str(file_path))
            if not content or len(content.strip()) < 10:
                self.logger.debug(f"No content extracted from: {file_path}")
                return False

            # Compute file hash if not provided
            file_hash = file_info.get('file_hash')
            if not file_hash:
                file_hash = compute_file_hash(str(file_path))

            # Build metadata
            metadata = {
                'filename': file_info['filename'],
                'source': self.source_name,
                'file_path': file_info.get('file_path', str(file_path)),
                'file_size': file_info.get('file_size'),
            }

            # Add any extra metadata from file_info
            if file_info.get('metadata'):
                metadata.update(file_info['metadata'])

            # Index in search engine (Voyage + Pinecone) if available
            if search_engine:
                search_engine.index_document(
                    doc_id=file_hash,
                    content=content,
                    metadata=metadata
                )

            # Save to SQLite database
            import json
            upsert_file(
                filename=file_info['filename'],
                file_path=file_info.get('file_path', str(file_path)),
                source=self.source_name,
                file_hash=file_hash,
                pinecone_id=file_hash,
                file_size=file_info.get('file_size'),
                metadata=json.dumps(metadata)
            )

            self.logger.info(f"Indexed: {file_info['filename']}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to index {file_info['filename']}: {e}")
            return False

    def index_content(
        self,
        content: str,
        metadata: Dict[str, Any],
        search_engine: SearchEngine = None
    ) -> bool:
        """
        Index arbitrary content (for emails, notes, etc.).

        Args:
            content: Text content to index
            metadata: Must include 'filename', 'source', 'file_path'
            search_engine: SearchEngine instance (uses singleton if not provided)

        Returns:
            True if indexed successfully
        """
        if search_engine is None:
            search_engine = get_search_engine()

        try:
            if not content or len(content.strip()) < 10:
                return False

            # Generate unique ID from content
            doc_id = hashlib.sha256(content.encode()).hexdigest()

            # Ensure required fields
            metadata['source'] = metadata.get('source', self.source_name)

            # Index in search engine if available
            if search_engine:
                search_engine.index_document(
                    doc_id=doc_id,
                    content=content,
                    metadata=metadata
                )

            # Save to SQLite
            import json
            upsert_file(
                filename=metadata.get('filename', 'Untitled'),
                file_path=metadata.get('file_path', ''),
                source=metadata['source'],
                file_hash=doc_id,
                pinecone_id=doc_id,
                metadata=json.dumps(metadata)
            )

            return True

        except Exception as e:
            self.logger.error(f"Failed to index content: {e}")
            return False

    def is_authenticated(self) -> bool:
        """
        Check if service is authenticated.

        Returns:
            True if authenticated, False otherwise
        """
        # Override in subclasses that need OAuth
        return True

    def cleanup_deleted_files(self, search_engine: SearchEngine = None) -> int:
        """
        Remove deleted files from the index (for local sources like Finder).

        Args:
            search_engine: SearchEngine instance

        Returns:
            Number of files cleaned up
        """
        import os
        from database.models import get_files_by_source, get_db_connection

        if search_engine is None:
            search_engine = get_search_engine()

        # Only run cleanup for local sources (Finder)
        if self.source_name != 'Finder':
            return 0

        cleaned = 0
        files = get_files_by_source(self.source_name)

        if not files:
            return 0

        for f in files:
            file_path = f.get('file_path')
            if file_path and not os.path.exists(file_path):
                self.logger.info(f"Cleaning up deleted file: {f.get('filename')}")

                # Remove from Pinecone
                pinecone_id = f.get('pinecone_id') or f.get('file_hash')
                if pinecone_id and search_engine:
                    try:
                        search_engine.delete_document(pinecone_id)
                    except Exception as e:
                        self.logger.warning(f"Failed to delete from Pinecone: {e}")

                # Mark as deleted in database
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE files SET is_deleted = 1 WHERE file_hash = ?",
                    (f.get('file_hash'),)
                )
                conn.commit()
                # Don't close - using thread-local connections

                cleaned += 1

        if cleaned > 0:
            self.logger.info(f"Cleaned up {cleaned} deleted files from {self.source_name}")

        return cleaned
