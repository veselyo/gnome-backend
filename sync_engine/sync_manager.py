"""
Sync manager - orchestrates all sync sources.
"""
from typing import Dict, List
import threading
import time
import logging
from database.models import GnomeDatabase
from sync_engine.finder_sync import FinderSyncEngine
from sync_engine.gdrive_sync import GoogleDriveSyncEngine
from sync_engine.onedrive_sync import OneDriveSyncEngine

logger = logging.getLogger(__name__)


class SyncManager:
    """Manages all sync sources and coordinates indexing."""
    
    def __init__(self, database: GnomeDatabase, voyage_client, pinecone_idx, namespace: str):
        """
        Initialize sync manager.
        
        Args:
            database: GnomeDatabase instance
            voyage_client: Voyage AI client
            pinecone_idx: Pinecone index
            namespace: User's Pinecone namespace
        """
        self.db = database
        self.voyage_client = voyage_client
        self.pinecone_idx = pinecone_idx
        self.namespace = namespace
        
        # Initialize sync engines
        self.engines = {
            'Finder': FinderSyncEngine(database),
            'Google Drive': GoogleDriveSyncEngine(database),
            'OneDrive': OneDriveSyncEngine(database)
        }
        
        self.is_syncing = False
        self.sync_interval = 300  # 5 minutes
        self.sync_thread = None
        self.max_files_per_sync = 200  # Process 200 files per sync (adaptive to total file count)
    
    def sync_all(self) -> Dict[str, Dict]:
        """
        Sync all sources with adaptive batch sizing.
        
        Returns:
            Dict with results for each source
        """
        results = {}
        
        for source_name, engine in self.engines.items():
            try:
                # Check if source is enabled
                sync_state = self.db.get_sync_state(source_name)
                if sync_state and not sync_state.get('enabled', True):
                    logger.info(f"Skipping disabled source: {source_name}")
                    continue
                
                # Check if authenticated (for cloud services)
                if not engine.is_authenticated():
                    logger.warning(f"{source_name} not authenticated, skipping")
                    results[source_name] = {'error': 'Not authenticated'}
                    continue
                
                # Adaptive batch size: process more files initially, fewer later
                indexed_count = len(self.db.get_files_by_source(source_name))
                if indexed_count < 100:
                    max_files = 500  # Index fast initially
                elif indexed_count < 500:
                    max_files = 200  # Medium speed
                else:
                    max_files = 50  # Slower for maintenance
                
                # Run sync with adaptive file limit
                result = engine.sync(
                    self.voyage_client,
                    self.pinecone_idx,
                    self.namespace,
                    max_files=max_files
                )
                results[source_name] = result
                
            except Exception as e:
                logger.error(f"Sync failed for {source_name}: {e}")
                results[source_name] = {'error': str(e)}
        
        return results
    
    def sync_source(self, source_name: str) -> Dict:
        """
        Sync a specific source.
        
        Args:
            source_name: Name of the source ('Finder', 'Google Drive', 'OneDrive')
        
        Returns:
            Sync results dict
        """
        if source_name not in self.engines:
            raise ValueError(f"Unknown source: {source_name}")
        
        engine = self.engines[source_name]
        return engine.sync(self.voyage_client, self.pinecone_idx, self.namespace)
    
    def start_auto_sync(self):
        """Start automatic syncing in background thread."""
        if self.is_syncing:
            logger.warning("Auto-sync already running")
            return
        
        self.is_syncing = True
        self.sync_thread = threading.Thread(target=self._auto_sync_loop, daemon=True)
        self.sync_thread.start()
        logger.info("Auto-sync started")
    
    def stop_auto_sync(self):
        """Stop automatic syncing."""
        self.is_syncing = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
        logger.info("Auto-sync stopped")
    
    def _auto_sync_loop(self):
        """Background loop for automatic syncing."""
        while self.is_syncing:
            try:
                logger.info("Running automatic sync...")
                self.sync_all()
                logger.info(f"Next sync in {self.sync_interval} seconds")
            except Exception as e:
                logger.error(f"Auto-sync error: {e}")
            
            # Sleep in small chunks so we can stop quickly
            for _ in range(self.sync_interval):
                if not self.is_syncing:
                    break
                time.sleep(1)
    
    def get_all_files(self) -> List[Dict]:
        """Get all indexed files from database."""
        return self.db.get_all_files()
    
    def get_files_by_source(self, source_name: str) -> List[Dict]:
        """Get files from specific source."""
        return self.db.get_files_by_source(source_name)
    
    def connect_google_drive(self) -> bool:
        """Initiate Google Drive OAuth connection."""
        try:
            engine = self.engines['Google Drive']
            success = engine.authenticate()
            if success:
                # Trigger immediate sync after connection
                logger.info("Google Drive connected, starting sync...")
                threading.Thread(
                    target=lambda: engine.sync(self.voyage_client, self.pinecone_idx, self.namespace, max_files=20),
                    daemon=True
                ).start()
            return success
        except Exception as e:
            logger.error(f"Google Drive connection failed: {e}")
            return False
    
    def connect_onedrive(self) -> bool:
        """Initiate OneDrive OAuth connection."""
        try:
            engine = self.engines['OneDrive']
            success = engine.authenticate()
            if success:
                # Trigger immediate sync after connection
                logger.info("OneDrive connected, starting sync...")
                threading.Thread(
                    target=lambda: engine.sync(self.voyage_client, self.pinecone_idx, self.namespace, max_files=20),
                    daemon=True
                ).start()
            return success
        except Exception as e:
            logger.error(f"OneDrive connection failed: {e}")
            return False
    
    def disconnect_source(self, source_name: str):
        """Disconnect a cloud source and remove its files."""
        if source_name == 'Finder':
            logger.warning("Cannot disconnect Finder")
            return
        
        # Delete OAuth tokens
        service_name = source_name.lower().replace(' ', '_')
        self.db.delete_oauth_token(service_name)
        
        # Mark all files from this source as deleted
        cursor = self.db.conn.cursor()
        cursor.execute("UPDATE files SET is_deleted = 1 WHERE source = ?", (source_name,))
        deleted_count = cursor.rowcount
        
        # Delete sync state so it shows as "never_synced" / not connected
        cursor.execute("DELETE FROM sync_state WHERE source = ?", (source_name,))
        
        self.db.conn.commit()
        
        logger.info(f"Disconnected {source_name} and removed {deleted_count} files")
    
    def get_sync_status(self) -> Dict:
        """Get sync status for all sources."""
        status = {}
        for source_name in self.engines.keys():
            sync_state = self.db.get_sync_state(source_name)
            if sync_state:
                status[source_name] = {
                    'last_sync': sync_state.get('last_sync'),
                    'status': sync_state.get('status', 'idle'),
                    'enabled': sync_state.get('enabled', True),
                    'error': sync_state.get('error_message')
                }
            else:
                status[source_name] = {
                    'status': 'never_synced',
                    'enabled': True
                }
        
        return status

