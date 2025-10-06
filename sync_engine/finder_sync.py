"""
Finder sync engine - watches local folders for PDF files.
"""
from pathlib import Path
from typing import List, Dict, Optional
import os
import logging
from datetime import datetime
from sync_engine.base_sync import BaseSyncEngine
from database.models import compute_file_hash


class FinderSyncEngine(BaseSyncEngine):
    """Sync engine for local Finder files."""
    
    def __init__(self, database):
        super().__init__(database, 'Finder')
        
        # Default folders to watch
        self.default_folders = [
            Path.home() / 'Documents',
            Path.home() / 'Downloads',
            Path.home() / 'Desktop'
        ]
    
    def authenticate(self) -> bool:
        """Finder doesn't need authentication."""
        return True
    
    def fetch_files(self) -> List[Dict]:
        """
        Scan watched folders for supported file types (PDFs, DOCX, TXT, etc.).
        
        Returns:
            List of file info dicts
        """
        from semantic_search.file_processor import get_supported_extensions
        
        files = []
        watched_folders = self.db.get_watched_folders('Finder')
        
        # If no watched folders, use defaults
        folders_to_scan = []
        if watched_folders:
            folders_to_scan = [Path(wf['folder_path']) for wf in watched_folders]
        else:
            folders_to_scan = self.default_folders
            # Add defaults to database
            for folder in self.default_folders:
                if folder.exists():
                    self.db.add_watched_folder('Finder', str(folder), recursive=True)
        
        # Get supported file extensions
        supported_exts = get_supported_extensions()
        
        # Scan each folder
        for folder in folders_to_scan:
            if not folder.exists():
                self.logger.warning(f"Folder does not exist: {folder}")
                continue
            
            try:
                # Find all supported files recursively
                for ext in supported_exts:
                    pattern = f'*{ext}'
                    for file_path in folder.rglob(pattern):
                        try:
                            stat = file_path.stat()
                            file_hash = compute_file_hash(str(file_path))
                            
                            files.append({
                                'filename': file_path.name,
                                'file_path': str(file_path),
                                'file_size': stat.st_size,
                                'last_modified': datetime.fromtimestamp(stat.st_mtime),
                                'file_hash': file_hash,
                                'metadata': {
                                    'folder': str(file_path.parent),
                                    'extension': file_path.suffix
                                }
                            })
                        except Exception as e:
                            self.logger.warning(f"Error reading {file_path}: {e}")
                            continue
                        
            except Exception as e:
                self.logger.error(f"Error scanning folder {folder}: {e}")
                continue
        
        # Sort by modification date (newest first) so new files get indexed first
        files.sort(key=lambda f: f['last_modified'], reverse=True)
        
        return files
    
    def download_file(self, file_info: Dict) -> Optional[Path]:
        """
        For Finder, file is already local.
        
        Args:
            file_info: File information dict
        
        Returns:
            Path to the local file
        """
        file_path = Path(file_info['file_path'])
        if file_path.exists():
            return file_path
        return None
    
    def add_watched_folder(self, folder_path: str):
        """Add a new folder to watch."""
        folder = Path(folder_path)
        if not folder.exists():
            raise ValueError(f"Folder does not exist: {folder_path}")
        
        self.db.add_watched_folder('Finder', str(folder), recursive=True)
        self.logger.info(f"Added watched folder: {folder_path}")
    
    def remove_watched_folder(self, folder_path: str):
        """Remove a folder from watch list."""
        # Implement if needed
        pass


# File system watcher using watchdog (for real-time updates)
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    
    class PDFWatchHandler(FileSystemEventHandler):
        """Handler for PDF file changes."""
        
        def __init__(self, finder_sync, voyage_client, pinecone_idx, namespace):
            self.finder_sync = finder_sync
            self.voyage_client = voyage_client
            self.pinecone_idx = pinecone_idx
            self.namespace = namespace
        
        def on_created(self, event):
            """Handle new file creation."""
            if not event.is_directory and event.src_path.endswith('.pdf'):
                self.finder_sync.logger.info(f"New PDF detected: {event.src_path}")
                # Trigger indexing
                # (Implementation would go here)
        
        def on_modified(self, event):
            """Handle file modification."""
            if not event.is_directory and event.src_path.endswith('.pdf'):
                self.finder_sync.logger.info(f"PDF modified: {event.src_path}")
                # Re-index if needed
    
    WATCHDOG_AVAILABLE = True
    
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("watchdog not installed - real-time file watching disabled")

