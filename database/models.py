"""
Database models for Gnome file tracking and sync state.
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import hashlib
import json
import threading

# Global database connection for helper functions
_DB_PATH = None

# Thread-local storage for database connections (prevents SQLite threading issues)
_local = threading.local()
_db_lock = threading.Lock()


def get_db_path() -> str:
    """Get the database path."""
    global _DB_PATH
    if _DB_PATH is None:
        app_data = Path.home() / '.gnome'
        app_data.mkdir(exist_ok=True)
        _DB_PATH = str(app_data / 'gnome.db')
    return _DB_PATH


def get_db_connection() -> sqlite3.Connection:
    """Get a thread-local database connection.

    Each thread gets its own connection to prevent SQLite threading issues.
    Connections are reused within the same thread.

    IMPORTANT: We do NOT use check_same_thread=False because thread-local
    storage already ensures each thread gets its own connection. Using
    check_same_thread=False can cause heap corruption when connections
    are accidentally shared across threads.
    """
    if not hasattr(_local, 'connection') or _local.connection is None:
        with _db_lock:
            # Double-check after acquiring lock
            if not hasattr(_local, 'connection') or _local.connection is None:
                _local.connection = sqlite3.connect(
                    get_db_path(),
                    # Removed check_same_thread=False - thread-local handles this
                    # Setting it to False can cause heap corruption crashes
                    timeout=30.0  # Wait up to 30 seconds for lock
                )
                _local.connection.row_factory = sqlite3.Row
    return _local.connection


class GnomeDatabase:
    """Main database interface for Gnome.

    This class uses a reentrant lock (RLock) to ensure thread-safe access
    to the database connection. All public methods acquire the lock before
    accessing the database.

    IMPORTANT: We use RLock instead of Lock because some methods may call
    other methods that also need the lock (e.g., init_schema calls execute).
    """

    # Class-level lock for thread safety
    _class_lock = threading.Lock()

    def __init__(self, db_path: str = None):
        """Initialize database connection."""
        if db_path is None:
            # Default to user's app data directory
            app_data = Path.home() / '.gnome'
            app_data.mkdir(exist_ok=True)
            db_path = str(app_data / 'gnome.db')

        self.db_path = db_path
        # Use RLock (reentrant lock) to allow the same thread to acquire
        # the lock multiple times (needed for nested method calls)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(
            db_path,
            # Keep check_same_thread=False for GnomeDatabase since it's
            # a singleton that IS shared across threads, but we protect
            # all access with self._lock
            check_same_thread=False,
            timeout=30.0  # Wait up to 30 seconds for lock
        )
        self.conn.row_factory = sqlite3.Row
        self.init_schema()
    
    def init_schema(self):
        """Create database tables if they don't exist."""
        with self._lock:
            cursor = self.conn.cursor()

            # Files table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    source TEXT NOT NULL,
                    file_hash TEXT UNIQUE NOT NULL,
                    pinecone_id TEXT UNIQUE NOT NULL,
                    file_size INTEGER,
                    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_modified TIMESTAMP,
                    is_deleted BOOLEAN DEFAULT 0,
                    metadata TEXT
                )
            ''')

            # Sync state table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sync_state (
                    source TEXT PRIMARY KEY,
                    last_sync TIMESTAMP,
                    status TEXT,
                    cursor TEXT,
                    enabled BOOLEAN DEFAULT 1,
                    error_message TEXT
                )
            ''')

            # OAuth tokens table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    service TEXT PRIMARY KEY,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Watched folders table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS watched_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    folder_path TEXT NOT NULL,
                    recursive BOOLEAN DEFAULT 1,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_source ON files(source)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_hash ON files(file_hash)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(is_deleted)')

            self.conn.commit()

    # File operations
    def add_file(self, filename: str, file_path: str, source: str,
                 file_hash: str, pinecone_id: str, file_size: int = None,
                 metadata: dict = None) -> int:
        """Add a new file to the database."""
        import json
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO files (filename, file_path, source, file_hash, pinecone_id,
                                 file_size, last_modified, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (filename, file_path, source, file_hash, pinecone_id,
                  file_size, datetime.now().isoformat(),
                  json.dumps(metadata) if metadata else None))
            self.conn.commit()
            return cursor.lastrowid

    def get_file_by_hash(self, file_hash: str) -> Optional[Dict]:
        """Check if file already exists by hash."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM files WHERE file_hash = ? AND is_deleted = 0',
                          (file_hash,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_files_by_source(self, source: str) -> List[Dict]:
        """Get all files from a specific source."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files
                WHERE source = ? AND is_deleted = 0
                ORDER BY last_modified DESC
            ''', (source,))
            return [dict(row) for row in cursor.fetchall()]

    def get_all_files(self) -> List[Dict]:
        """Get all active files."""
        import json
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files
                WHERE is_deleted = 0
                ORDER BY last_modified DESC
            ''')
            files = []
            for row in cursor.fetchall():
                file_dict = dict(row)
                # Parse metadata JSON if present
                if file_dict.get('metadata'):
                    try:
                        file_dict['metadata'] = json.loads(file_dict['metadata'])
                    except:
                        file_dict['metadata'] = {}
                files.append(file_dict)
            return files
    
    def get_all_indexed_files(self) -> List[Dict]:
        """Get all indexed (searchable) files - files that have a Pinecone ID."""
        import json
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM files
                WHERE is_deleted = 0 AND pinecone_id IS NOT NULL AND pinecone_id != ''
                ORDER BY last_modified DESC
            ''')
            files = []
            for row in cursor.fetchall():
                file_dict = dict(row)
                # Parse metadata JSON if present
                if file_dict.get('metadata'):
                    try:
                        file_dict['metadata'] = json.loads(file_dict['metadata'])
                    except:
                        file_dict['metadata'] = {}
                files.append(file_dict)
            return files

    def mark_file_deleted(self, file_id: int):
        """Mark a file as deleted (soft delete)."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('UPDATE files SET is_deleted = 1 WHERE id = ?', (file_id,))
            self.conn.commit()

    # Sync state operations
    def update_sync_state(self, source: str, status: str, cursor_value: str = None,
                         error: str = None):
        """Update sync state for a source."""
        with self._lock:
            cursor_obj = self.conn.cursor()
            cursor_obj.execute('''
                INSERT INTO sync_state (source, last_sync, status, cursor, error_message)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_sync = excluded.last_sync,
                    status = excluded.status,
                    cursor = excluded.cursor,
                    error_message = excluded.error_message
            ''', (source, datetime.now().isoformat(), status, cursor_value, error))
            self.conn.commit()

    def get_sync_state(self, source: str) -> Optional[Dict]:
        """Get sync state for a source."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM sync_state WHERE source = ?', (source,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # OAuth token operations
    def save_oauth_token(self, service: str, access_token: str,
                        refresh_token: str = None, expires_at: str = None):
        """Save OAuth tokens for a service."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO oauth_tokens (service, access_token, refresh_token, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(service) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
            ''', (service, access_token, refresh_token, expires_at,
                  datetime.now().isoformat()))
            self.conn.commit()

    def get_oauth_token(self, service: str) -> Optional[Dict]:
        """Get OAuth token for a service."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM oauth_tokens WHERE service = ?', (service,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_oauth_token(self, service: str):
        """Delete OAuth token (disconnect service)."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM oauth_tokens WHERE service = ?', (service,))
            self.conn.commit()

    # Watched folders operations
    def add_watched_folder(self, source: str, folder_path: str, recursive: bool = True):
        """Add a folder to watch list."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO watched_folders (source, folder_path, recursive)
                VALUES (?, ?, ?)
            ''', (source, folder_path, recursive))
            self.conn.commit()
            return cursor.lastrowid

    def get_watched_folders(self, source: str) -> List[Dict]:
        """Get all watched folders for a source."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM watched_folders
                WHERE source = ? AND enabled = 1
            ''', (source,))
            return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close database connection."""
        with self._lock:
            self.conn.close()


def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


# ============ Helper functions for sync engines ============

def upsert_file(
    filename: str,
    file_path: str,
    source: str,
    file_hash: str,
    pinecone_id: str,
    file_size: int = None,
    metadata: str = None
) -> int:
    """
    Insert or update a file record.

    Args:
        filename: Name of the file
        file_path: Path or URL to the file
        source: Source name (Finder, Gmail, etc.)
        file_hash: SHA256 hash for deduplication
        pinecone_id: ID in Pinecone vector database
        file_size: Optional file size in bytes
        metadata: Optional JSON string with additional metadata

    Returns:
        Row ID of the inserted/updated record
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO files (filename, file_path, source, file_hash, pinecone_id,
                          file_size, last_modified, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_hash) DO UPDATE SET
            filename = excluded.filename,
            file_path = excluded.file_path,
            pinecone_id = excluded.pinecone_id,
            last_modified = excluded.last_modified,
            metadata = excluded.metadata,
            is_deleted = 0
    ''', (filename, file_path, source, file_hash, pinecone_id,
          file_size, datetime.now().isoformat(), metadata))

    conn.commit()
    row_id = cursor.lastrowid
    # Don't close - using thread-local connections
    return row_id


def get_oauth_token(service: str) -> Optional[Dict[str, Any]]:
    """
    Get OAuth token for a service.

    Args:
        service: Service name (gmail, google_drive, outlook, etc.)

    Returns:
        Dict with token data or None if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM oauth_tokens WHERE service = ?', (service,))
    row = cursor.fetchone()
    # Don't close - using thread-local connections

    if row:
        result = dict(row)
        # Parse extra_data JSON if present
        if result.get('extra_data'):
            try:
                extra = json.loads(result['extra_data'])
                result.update(extra)
            except:
                pass
        return result
    return None


def save_oauth_token(
    service: str,
    access_token: str,
    refresh_token: str = None,
    expires_at: str = None,
    extra_data: Dict[str, Any] = None
):
    """
    Save OAuth token for a service.

    Args:
        service: Service name (gmail, google_drive, outlook, etc.)
        access_token: OAuth access token
        refresh_token: Optional refresh token
        expires_at: Optional expiration timestamp (ISO format)
        extra_data: Optional additional data (client_id, client_secret, etc.)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Ensure the table has extra_data column
    try:
        cursor.execute('ALTER TABLE oauth_tokens ADD COLUMN extra_data TEXT')
    except sqlite3.OperationalError:
        pass  # Column already exists

    extra_json = json.dumps(extra_data) if extra_data else None

    cursor.execute('''
        INSERT INTO oauth_tokens (service, access_token, refresh_token, expires_at, extra_data, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET
            access_token = excluded.access_token,
            refresh_token = COALESCE(excluded.refresh_token, oauth_tokens.refresh_token),
            expires_at = excluded.expires_at,
            extra_data = COALESCE(excluded.extra_data, oauth_tokens.extra_data),
            updated_at = excluded.updated_at
    ''', (service, access_token, refresh_token, expires_at, extra_json,
          datetime.now().isoformat()))

    conn.commit()
    # Don't close - using thread-local connections


def delete_oauth_token(service: str):
    """Delete OAuth token for a service."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM oauth_tokens WHERE service = ?', (service,))
    conn.commit()
    # Don't close - using thread-local connections


def get_sync_state(source: str) -> Optional[Dict[str, Any]]:
    """Get sync state for a source."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM sync_state WHERE source = ?', (source,))
    row = cursor.fetchone()
    # Don't close - using thread-local connections
    return dict(row) if row else None


def update_sync_state(
    source: str,
    status: str,
    last_sync: str = None,
    error_message: str = None
):
    """Update sync state for a source."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if last_sync is None:
        last_sync = datetime.now().isoformat()

    cursor.execute('''
        INSERT INTO sync_state (source, last_sync, status, error_message, enabled)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(source) DO UPDATE SET
            last_sync = excluded.last_sync,
            status = excluded.status,
            error_message = excluded.error_message
    ''', (source, last_sync, status, error_message))

    conn.commit()
    # Don't close - using thread-local connections


def get_files_by_source(source: str) -> List[Dict[str, Any]]:
    """Get all files from a specific source."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM files
        WHERE source = ? AND is_deleted = 0
        ORDER BY last_modified DESC
    ''', (source,))
    files = [dict(row) for row in cursor.fetchall()]
    # Don't close - using thread-local connections
    return files


def get_file_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    """Get a file by its hash."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM files WHERE file_hash = ? AND is_deleted = 0', (file_hash,))
    row = cursor.fetchone()
    # Don't close - using thread-local connections
    return dict(row) if row else None


def clear_source_files(source: str) -> int:
    """
    Clear all files and watched folders for a source.
    Use this to reset a source and allow fresh re-indexing.

    Args:
        source: Source name (e.g., 'Finder', 'Google Drive')

    Returns:
        Number of files deleted
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Count files to be deleted
    cursor.execute("SELECT COUNT(*) FROM files WHERE source = ?", (source,))
    file_count = cursor.fetchone()[0]

    # Delete all files for this source
    cursor.execute("DELETE FROM files WHERE source = ?", (source,))

    # Delete watched folders for this source
    cursor.execute("DELETE FROM watched_folders WHERE source = ?", (source,))

    # Reset sync state
    cursor.execute("DELETE FROM sync_state WHERE source = ?", (source,))

    conn.commit()
    return file_count


def init_database():
    """Initialize the database schema."""
    db = GnomeDatabase()
    db.close()
    return db

