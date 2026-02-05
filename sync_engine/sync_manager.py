"""
Sync Manager - Orchestrates all 5 sync sources.
Unified interface for Voyage AI + Pinecone cloud architecture.
"""
from typing import Dict, List, Optional, Any
import threading
import time
import logging
from datetime import datetime

from database.models import (
    GnomeDatabase, get_db_connection, update_sync_state,
    get_oauth_token, get_files_by_source
)
from semantic_search.search_engine import SearchEngine, get_search_engine

# Import all sync engines
from sync_engine.finder_sync import FinderSyncEngine
from sync_engine.gdrive_sync import GoogleDriveSyncEngine
from sync_engine.onedrive_sync import OneDriveSyncEngine
from sync_engine.gmail_sync import GmailSyncEngine
from sync_engine.outlook_sync import OutlookSyncEngine

logger = logging.getLogger(__name__)


# Source categories for UI organization
SOURCE_CATEGORIES = {
    "local": ["Finder"],
    "cloud": ["Google Drive", "OneDrive", "Gmail", "Outlook"]
}

# Sources that require OAuth
OAUTH_SOURCES = {
    "Google Drive": "google_drive",
    "Gmail": "gmail",
    "OneDrive": "onedrive",
    "Outlook": "outlook"
}


class SyncManager:
    """Manages all sync sources and coordinates indexing."""

    def __init__(self, database: GnomeDatabase):
        """
        Initialize sync manager with all 5 sources.

        Args:
            database: GnomeDatabase instance
        """
        self.db = database
        self.search_engine = get_search_engine()  # May be None if cloud not configured

        if self.search_engine is None:
            logger.warning("Search engine unavailable - sync will track files but not index them")

        # Initialize all sync engines (5 sources)
        self.engines = {
            # Local sources
            'Finder': FinderSyncEngine(database),
            # Cloud sources
            'Google Drive': GoogleDriveSyncEngine(database),
            'OneDrive': OneDriveSyncEngine(database),
            'Gmail': GmailSyncEngine(database),
            'Outlook': OutlookSyncEngine(database)
        }

        self.is_syncing = False
        self.sync_interval = 300  # 5 minutes
        self.sync_thread = None
        self._sync_lock = threading.Lock()

        # Per-source locks to prevent concurrent syncs of the same source
        # This prevents heap corruption from multiple threads accessing the same service
        self._source_locks: Dict[str, threading.Lock] = {}

        # Track which sources are currently syncing (to avoid crashes on disconnect)
        self._active_syncs: set = set()
        self._disconnected_sources: set = set()  # Sources being disconnected

        logger.info(f"SyncManager initialized with {len(self.engines)} sources")

    def get_source_status(self, source_name: str) -> Dict[str, Any]:
        """
        Get detailed status for a source.

        Returns:
            Dict with: connected, authenticated, last_sync, file_count, status, error
        """
        if source_name not in self.engines:
            return {"error": f"Unknown source: {source_name}"}

        engine = self.engines[source_name]

        # Get file count from database
        files = get_files_by_source(source_name)
        file_count = len(files) if files else 0

        # Check authentication status
        is_authenticated = engine.is_authenticated()

        # Get sync state
        sync_state = self.db.get_sync_state(source_name)

        status = {
            "source": source_name,
            "connected": is_authenticated,
            "authenticated": is_authenticated,
            "file_count": file_count,
            "last_sync": sync_state.get('last_sync') if sync_state else None,
            "status": sync_state.get('status', 'idle') if sync_state else 'never_synced',
            "error": sync_state.get('error_message') if sync_state else None,
            "requires_oauth": source_name in OAUTH_SOURCES,
            "category": "local" if source_name in SOURCE_CATEGORIES["local"] else "cloud"
        }

        return status

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status for all sources."""
        return {name: self.get_source_status(name) for name in self.engines.keys()}

    def _get_source_lock(self, source: str) -> threading.Lock:
        """Get or create a lock for a specific source (thread-safe)."""
        if source not in self._source_locks:
            with self._sync_lock:
                # Double-check after acquiring lock
                if source not in self._source_locks:
                    self._source_locks[source] = threading.Lock()
        return self._source_locks[source]

    def sync_source(
        self,
        source_name: str,
        max_files: int = 500,
        force: bool = False
    ) -> Dict[str, int]:
        """
        Sync a specific source with per-source locking.

        Uses non-blocking lock acquisition to prevent concurrent syncs of
        the same source, which can cause heap corruption when multiple
        threads access the same Google/Microsoft API service object.

        Args:
            source_name: Name of the source
            max_files: Maximum files to process
            force: Force sync even if recently synced

        Returns:
            Sync stats dict
        """
        logger.info(f"sync_source({source_name}) called with max_files={max_files}")

        if source_name not in self.engines:
            raise ValueError(f"Unknown source: {source_name}")

        # Check if source is being disconnected
        if source_name in self._disconnected_sources:
            logger.info(f"Skipping sync for {source_name} - source is being disconnected")
            return {'status': 'cancelled', 'reason': 'disconnected'}

        engine = self.engines[source_name]
        logger.info(f"Got engine for {source_name}: {type(engine).__name__}")

        # Check authentication
        is_auth = engine.is_authenticated()
        logger.info(f"{source_name} is_authenticated() = {is_auth}")
        if not is_auth:
            raise RuntimeError(f"{source_name} not authenticated")

        # Get per-source lock - prevents concurrent syncs of same source
        source_lock = self._get_source_lock(source_name)

        # Try to acquire lock non-blocking - if can't, another sync is in progress
        if not source_lock.acquire(blocking=False):
            logger.info(f"Sync already in progress for {source_name}, skipping")
            return {'status': 'skipped', 'reason': 'sync_in_progress'}

        try:
            # Track that this source is syncing
            self._active_syncs.add(source_name)

            # Update sync state to syncing
            update_sync_state(source_name, 'syncing', datetime.now().isoformat())

            # Check again before starting (race condition protection)
            if source_name in self._disconnected_sources:
                logger.info(f"Sync cancelled for {source_name} - source disconnected")
                return {'status': 'cancelled', 'reason': 'disconnected'}

            # Run sync with search engine
            logger.info(f"Calling engine.sync() for {source_name} with search_engine={self.search_engine is not None}")
            result = engine.sync(
                search_engine=self.search_engine,
                max_files=max_files
            )

            # Update sync state to idle
            update_sync_state(source_name, 'idle', datetime.now().isoformat())

            logger.info(f"Sync complete for {source_name}: {result}")
            return result

        except Exception as e:
            # Check if this was due to disconnect (don't log as error)
            if source_name in self._disconnected_sources:
                logger.info(f"Sync stopped for {source_name} due to disconnect")
                return {'status': 'cancelled', 'reason': 'disconnected'}
            logger.error(f"Sync failed for {source_name}: {e}")
            update_sync_state(source_name, 'error', datetime.now().isoformat(), str(e))
            raise

        finally:
            # Remove from active syncs
            self._active_syncs.discard(source_name)
            # Always release the lock
            source_lock.release()

    def sync_all(self, max_files_per_source: int = 200) -> Dict[str, Dict]:
        """
        Sync all enabled and authenticated sources with per-source locking.

        Uses non-blocking lock acquisition to skip sources that are already
        being synced by another thread (e.g., OAuth callback triggered sync).

        Args:
            max_files_per_source: Max files to process per source

        Returns:
            Dict with results for each source
        """
        results = {}

        # Priority order: Google Drive first (user's primary storage), then others
        priority_order = [
            'Google Drive', 'Finder',
            'Gmail', 'Outlook',
            'OneDrive'
        ]

        for source_name in priority_order:
            if source_name not in self.engines:
                continue

            engine = self.engines[source_name]

            # Skip if source was disconnected
            if source_name in self._disconnected_sources:
                logger.info(f"Skipping {source_name} - disconnected")
                continue

            # Acquire per-source lock (non-blocking) to prevent concurrent syncs
            source_lock = self._get_source_lock(source_name)
            if not source_lock.acquire(blocking=False):
                logger.info(f"Sync already in progress for {source_name}, skipping")
                results[source_name] = {'status': 'skipped', 'reason': 'sync_in_progress'}
                continue

            try:
                # Check if source is enabled
                sync_state = self.db.get_sync_state(source_name)
                if sync_state and not sync_state.get('enabled', True):
                    logger.info(f"Skipping disabled source: {source_name}")
                    continue

                # Check authentication
                if not engine.is_authenticated():
                    logger.debug(f"{source_name} not authenticated, skipping")
                    results[source_name] = {'status': 'not_authenticated'}
                    continue

                # Adaptive batch sizing
                file_count = len(get_files_by_source(source_name) or [])
                if file_count < 100:
                    max_files = 500  # Fast initial indexing
                elif file_count < 500:
                    max_files = max_files_per_source
                else:
                    max_files = 100  # Maintenance mode

                # Run sync (now protected by per-source lock)
                result = engine.sync(
                    search_engine=self.search_engine,
                    max_files=max_files
                )
                results[source_name] = result

            except Exception as e:
                # Check if this was due to disconnect
                if source_name in self._disconnected_sources:
                    logger.info(f"Sync stopped for {source_name} due to disconnect")
                    results[source_name] = {'status': 'cancelled', 'reason': 'disconnected'}
                else:
                    logger.error(f"Sync failed for {source_name}: {e}")
                    results[source_name] = {'error': str(e)}

            finally:
                # CRITICAL: Always release the lock
                source_lock.release()

        return results

    def start_auto_sync(self, interval: int = 300):
        """
        Start automatic background syncing.

        Args:
            interval: Seconds between sync cycles
        """
        if self.is_syncing:
            logger.warning("Auto-sync already running")
            return

        self.sync_interval = interval
        self.is_syncing = True
        self.sync_thread = threading.Thread(target=self._auto_sync_loop, daemon=True)
        self.sync_thread.start()
        logger.info(f"Auto-sync started (interval: {interval}s)")

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
                with self._sync_lock:
                    logger.info("Running automatic sync...")
                    results = self.sync_all()
                    logger.info(f"Auto-sync complete: {results}")
            except Exception as e:
                logger.error(f"Auto-sync error: {e}")

            # Sleep in chunks for quick shutdown
            for _ in range(self.sync_interval):
                if not self.is_syncing:
                    break
                time.sleep(1)

    # ============ OAuth Connection Methods ============

    def _run_sync_with_logging(self, source: str, max_files: int):
        """
        Run sync with error logging.

        Daemon threads swallow exceptions silently, so this wrapper
        ensures any errors are logged for debugging.
        """
        try:
            logger.info(f"[SYNC THREAD] Starting initial sync for {source}...")
            result = self.sync_source(source, max_files=max_files)
            logger.info(f"[SYNC THREAD] Initial sync complete for {source}: {result}")
        except Exception as e:
            logger.error(f"[SYNC THREAD] Initial sync FAILED for {source}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def connect_google_drive(self) -> bool:
        """Initiate Google Drive OAuth connection."""
        try:
            engine = self.engines['Google Drive']
            success = engine.authenticate()
            if success:
                logger.info("Google Drive connected, starting initial sync...")
                threading.Thread(
                    target=self._run_sync_with_logging,
                    args=('Google Drive', 50),
                    daemon=True
                ).start()
            return success
        except Exception as e:
            logger.error(f"Google Drive connection failed: {e}")
            return False

    def connect_gmail(self) -> bool:
        """Initiate Gmail OAuth connection."""
        try:
            engine = self.engines['Gmail']
            success = engine.authenticate()
            if success:
                logger.info("Gmail connected, starting initial sync...")
                threading.Thread(
                    target=self._run_sync_with_logging,
                    args=('Gmail', 100),
                    daemon=True
                ).start()
            return success
        except Exception as e:
            logger.error(f"Gmail connection failed: {e}")
            return False

    def connect_onedrive(self) -> bool:
        """Initiate OneDrive OAuth connection."""
        try:
            engine = self.engines['OneDrive']
            success = engine.authenticate()
            if success:
                logger.info("OneDrive connected, starting initial sync...")
                threading.Thread(
                    target=self._run_sync_with_logging,
                    args=('OneDrive', 50),
                    daemon=True
                ).start()
            return success
        except Exception as e:
            logger.error(f"OneDrive connection failed: {e}")
            return False

    def connect_outlook(self) -> bool:
        """Initiate Outlook OAuth connection."""
        try:
            engine = self.engines['Outlook']
            # Outlook uses different auth flow - return auth URL
            auth_url = engine.get_auth_url()
            logger.info(f"Outlook auth URL: {auth_url}")
            # In practice, the frontend would open this URL
            # and handle the callback
            return True
        except Exception as e:
            logger.error(f"Outlook connection failed: {e}")
            return False

    def complete_outlook_auth(self, auth_code: str) -> bool:
        """Complete Outlook OAuth with authorization code."""
        try:
            engine = self.engines['Outlook']
            success = engine.authenticate_with_code(auth_code)
            if success:
                logger.info("Outlook connected, starting initial sync...")
                threading.Thread(
                    target=self._run_sync_with_logging,
                    args=('Outlook', 100),
                    daemon=True
                ).start()
            return success
        except Exception as e:
            logger.error(f"Outlook auth completion failed: {e}")
            return False

    def complete_onedrive_auth(self, auth_code: str) -> bool:
        """Complete OneDrive OAuth with authorization code."""
        try:
            engine = self.engines['OneDrive']
            success = engine.authenticate_with_code(auth_code)
            if success:
                logger.info("OneDrive connected, starting initial sync...")
                threading.Thread(
                    target=self._run_sync_with_logging,
                    args=('OneDrive', 50),
                    daemon=True
                ).start()
            return success
        except Exception as e:
            logger.error(f"OneDrive auth completion failed: {e}")
            return False

    def disconnect_source(self, source_name: str) -> bool:
        """
        Disconnect a source and remove its indexed files.

        Args:
            source_name: Name of the source to disconnect

        Returns:
            True if successful
        """
        if source_name not in self.engines:
            raise ValueError(f"Unknown source: {source_name}")

        if source_name == 'Finder':
            logger.warning("Cannot disconnect Finder")
            return False

        try:
            # FIRST: Mark source as disconnected to stop any active/new syncs
            self._disconnected_sources.add(source_name)
            logger.info(f"Marked {source_name} for disconnection")

            # Wait briefly for any active sync to notice and stop
            # This prevents SSL crashes from in-flight requests
            if source_name in self._active_syncs:
                logger.info(f"Waiting for active sync on {source_name} to stop...")
                for _ in range(10):  # Wait up to 1 second
                    if source_name not in self._active_syncs:
                        break
                    time.sleep(0.1)

            engine = self.engines[source_name]

            # Disconnect the engine (removes OAuth tokens)
            if hasattr(engine, 'disconnect'):
                engine.disconnect()

            # Delete files from Pinecone (if configured)
            if self.search_engine:
                try:
                    self.search_engine.delete_source(source_name)
                except Exception as e:
                    logger.warning(f"Could not delete from Pinecone: {e}")

            # Mark files as deleted in database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE files SET is_deleted = 1 WHERE source = ?",
                (source_name,)
            )
            deleted_count = cursor.rowcount

            # Delete sync state
            cursor.execute(
                "DELETE FROM sync_state WHERE source = ?",
                (source_name,)
            )

            conn.commit()
            # Don't close - using thread-local connections

            logger.info(f"Disconnected {source_name}, removed {deleted_count} files")
            return True

        except Exception as e:
            logger.error(f"Error disconnecting {source_name}: {e}")
            return False

        finally:
            # Remove from disconnected set after a delay (allow threads to fully stop)
            def cleanup():
                time.sleep(2)
                self._disconnected_sources.discard(source_name)
            threading.Thread(target=cleanup, daemon=True).start()

    # ============ Search Interface ============

    def search(
        self,
        query: str,
        top_k: int = 15,
        source_filter: Optional[str] = None,
        use_reranking: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search across all indexed sources.

        Args:
            query: Natural language search query
            top_k: Number of results to return
            source_filter: Optional filter by source name
            use_reranking: Whether to apply BM25 reranking

        Returns:
            List of search results with scores and metadata
        """
        if self.search_engine is None:
            logger.warning("Search unavailable - cloud services not configured")
            return []

        return self.search_engine.search(
            query=query,
            top_k=top_k,
            source_filter=source_filter,
            use_reranking=use_reranking
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        if self.search_engine is None:
            return {"error": "Cloud services not configured"}
        return self.search_engine.get_stats()

    def get_files_by_source(self, source_name: str) -> List[Dict]:
        """Get all files from a specific source."""
        return get_files_by_source(source_name) or []

    def get_all_files(self) -> List[Dict]:
        """Get all indexed files."""
        return self.db.get_all_files()


# Singleton instance
_MANAGER = None


def get_sync_manager(database: GnomeDatabase = None) -> SyncManager:
    """Get or create the singleton sync manager."""
    global _MANAGER
    if _MANAGER is None:
        if database is None:
            from database.models import GnomeDatabase
            database = GnomeDatabase()
        _MANAGER = SyncManager(database)
    return _MANAGER
