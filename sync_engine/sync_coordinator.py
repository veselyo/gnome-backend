"""
Sync coordinator to manage concurrent syncs and prevent conflicts.
"""
import threading
import logging
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SyncCoordinator:
    """Coordinates sync operations across multiple sources."""
    
    def __init__(self):
        self.locks = {
            'Finder': threading.Lock(),
            'Google Drive': threading.Lock(),
            'OneDrive': threading.Lock()
        }
        self.active_syncs = {}
        self.sync_history = []
        self.global_lock = threading.Lock()
    
    def can_sync(self, source: str) -> bool:
        """
        Check if a source can sync (not already syncing).
        
        Args:
            source: Source name
        
        Returns:
            True if can sync, False if already syncing
        """
        return not self.locks[source].locked()
    
    def start_sync(self, source: str) -> bool:
        """
        Attempt to start a sync for a source.
        
        Args:
            source: Source name
        
        Returns:
            True if sync started, False if already running
        """
        acquired = self.locks[source].acquire(blocking=False)
        if acquired:
            with self.global_lock:
                self.active_syncs[source] = {
                    'started': datetime.now(),
                    'status': 'running'
                }
            logger.info(f"🔒 Sync started for {source}")
        return acquired
    
    def end_sync(self, source: str, success: bool = True, error: Optional[str] = None):
        """
        Mark a sync as complete.
        
        Args:
            source: Source name
            success: Whether sync succeeded
            error: Error message if failed
        """
        if self.locks[source].locked():
            with self.global_lock:
                sync_info = self.active_syncs.get(source, {})
                sync_info['ended'] = datetime.now()
                sync_info['success'] = success
                sync_info['error'] = error
                
                # Calculate duration
                started = sync_info.get('started')
                if started:
                    duration = (datetime.now() - started).total_seconds()
                    sync_info['duration'] = duration
                
                # Add to history
                self.sync_history.append({
                    'source': source,
                    **sync_info
                })
                
                # Keep only last 100 syncs in history
                if len(self.sync_history) > 100:
                    self.sync_history = self.sync_history[-100:]
                
                # Remove from active
                if source in self.active_syncs:
                    del self.active_syncs[source]
            
            self.locks[source].release()
            logger.info(f"🔓 Sync ended for {source} (success={success})")
    
    def get_sync_status(self) -> Dict:
        """Get current sync status for all sources."""
        with self.global_lock:
            status = {}
            for source in self.locks.keys():
                is_syncing = self.locks[source].locked()
                sync_info = self.active_syncs.get(source)
                
                status[source] = {
                    'is_syncing': is_syncing,
                    'current_sync': sync_info if is_syncing else None
                }
                
                # Add last sync from history
                last_sync = next((s for s in reversed(self.sync_history) 
                                if s['source'] == source), None)
                if last_sync:
                    status[source]['last_sync'] = last_sync
            
            return status
    
    def wait_for_all(self, timeout: float = 60.0):
        """
        Wait for all active syncs to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
        """
        start = datetime.now()
        for source, lock in self.locks.items():
            remaining_time = timeout - (datetime.now() - start).total_seconds()
            if remaining_time <= 0:
                logger.warning(f"Timeout waiting for {source}")
                break
            
            if lock.locked():
                logger.info(f"Waiting for {source} sync to complete...")
                acquired = lock.acquire(timeout=remaining_time)
                if acquired:
                    lock.release()

