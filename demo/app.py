"""
Gnome Flask Backend - Voyage AI + Pinecone Cloud Architecture
Semantic search across 5 data sources: Finder, Google Drive, Gmail, OneDrive, Outlook.
"""
# CRITICAL: Load environment variables FIRST before any other imports
import os
import sys
from pathlib import Path

# Set up paths first
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Load environment variables from multiple possible locations
from dotenv import load_dotenv

env_paths = [
    ROOT_DIR / 'electron' / '.env',       # Development: project/electron/.env
    ROOT_DIR / '.env',                     # Alternative: project/.env
    Path.home() / '.gnome-env',            # Production: user home
]

env_loaded = False
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path, override=True)  # override=True ensures it overwrites existing
        print(f"✅ Loaded environment from: {env_path}")
        env_loaded = True
        break

if not env_loaded:
    load_dotenv()
    print("⚠️ No .env file found, using system environment variables")

# ============ PRODUCTION CONFIG (Baked In) ============
# These values are safe to include in the distributed app
# Only public identifiers - all secrets stay on the proxy server

# Proxy server URL - handles embeddings, search, and OAuth
PROXY_URL = 'https://gnome-production.up.railway.app'

# OAuth Client IDs (public identifiers - safe to include)
GOOGLE_CLIENT_ID = '200229085583-tasbpc46mnl4ahs2hj3ouqtmjf1jdnv5.apps.googleusercontent.com'
MICROSOFT_CLIENT_ID = '9ff39189-1c55-4b23-8cb2-fdeebffe1d70'

# Set config in environment for other modules to use
if not os.environ.get('PROXY_URL'):
    os.environ['PROXY_URL'] = PROXY_URL
if not os.environ.get('GOOGLE_CLIENT_ID'):
    os.environ['GOOGLE_CLIENT_ID'] = GOOGLE_CLIENT_ID
if not os.environ.get('MICROSOFT_CLIENT_ID'):
    os.environ['MICROSOFT_CLIENT_ID'] = MICROSOFT_CLIENT_ID

# Debug: Print configuration status
print(f"   GOOGLE_CLIENT_ID: ✓ baked in")
print(f"   MICROSOFT_CLIENT_ID: ✓ baked in")
print(f"   PROXY_URL: {PROXY_URL}")
print(f"   VOYAGE_API_KEY: {'✓ set (direct mode)' if os.environ.get('VOYAGE_API_KEY') else '✗ (using proxy)'}")
print(f"   PINECONE_API_KEY: {'✓ set (direct mode)' if os.environ.get('PINECONE_API_KEY') else '✗ (using proxy)'}")

# Now import everything else
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
)
import traceback
import secrets
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import socket
import json
import subprocess
import webbrowser
import threading
import hashlib
import platform
import uuid

# === GNOME MVP - Cloud-powered semantic search ===
# Voyage AI (voyage-3) + Pinecone vector database
# Supports 6 data sources

from semantic_search.search_engine import SearchEngine, get_search_engine
from semantic_search.file_processor import extract_text, is_supported_file
from database.models import GnomeDatabase, get_files_by_source
from sync_engine.sync_manager import SyncManager, get_sync_manager

# Flask setup
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = Path(__file__).resolve().parent / "uploads"
app.secret_key = secrets.token_hex(16)

UPLOAD_FOLDER: Path = app.config["UPLOAD_FOLDER"]
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# Check cloud services configuration
from semantic_search.search_engine import is_configured as cloud_configured

CLOUD_CONFIGURED = cloud_configured()
if CLOUD_CONFIGURED:
    app.logger.info("Initializing Gnome MVP - Voyage AI + Pinecone...")
else:
    app.logger.warning("Cloud services not configured - running in limited mode")
    app.logger.warning("Set VOYAGE_API_KEY and PINECONE_API_KEY to enable semantic search")

# Generate unique namespace per user
def get_user_namespace():
    """Generate a unique namespace for this user's machine."""
    is_packaged = getattr(sys, 'frozen', False) or 'app.asar' in sys.argv[0]

    if not is_packaged:
        return "demo"

    machine_id = str(uuid.getnode())
    hostname = platform.node()
    namespace_string = f"{machine_id}_{hostname}"
    namespace_hash = hashlib.sha256(namespace_string.encode()).hexdigest()[:16]
    return f"user_{namespace_hash}"

NAMESPACE = get_user_namespace()
app.logger.info(f"Using namespace: {NAMESPACE}")

# Initialize database and sync manager
DB = GnomeDatabase()
SYNC_MANAGER = get_sync_manager(DB)
SEARCH_ENGINE = get_search_engine()  # May be None if cloud not configured

if CLOUD_CONFIGURED:
    app.logger.info("Gnome MVP initialized with 5 data sources")
else:
    app.logger.info("Gnome MVP initialized in limited mode (no semantic search)")

# Start auto-sync in background (only if cloud configured)
if CLOUD_CONFIGURED and SYNC_MANAGER:
    SYNC_MANAGER.start_auto_sync()


def _run_initial_sync_thread(source: str, max_files: int):
    """
    Run initial sync after OAuth completes.

    This is a module-level function (not inside a route handler) to avoid
    closure issues with daemon threads. Daemon threads can't access Flask's
    app context properly if defined inside route handlers.
    """
    import traceback
    try:
        app.logger.info(f"[SYNC THREAD] Starting initial sync for {source}...")
        result = SYNC_MANAGER.sync_source(source, max_files=max_files)
        app.logger.info(f"[SYNC THREAD] Initial sync complete for {source}: {result}")
    except Exception as e:
        app.logger.error(f"[SYNC THREAD] Initial sync FAILED for {source}: {e}")
        app.logger.error(traceback.format_exc())


def _cleanup_deleted_files(deleted_files):
    """Clean up files that no longer exist from database and Pinecone."""
    from database.models import get_db_connection

    for f in deleted_files:
        try:
            pinecone_id = f.get('pinecone_id') or f.get('file_hash')

            # Remove from Pinecone
            if pinecone_id and SEARCH_ENGINE:
                try:
                    SEARCH_ENGINE.delete_document(pinecone_id)
                    app.logger.debug(f"Deleted from Pinecone: {f.get('filename')}")
                except Exception as e:
                    app.logger.warning(f"Failed to delete from Pinecone: {e}")

            # Mark as deleted in database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE files SET is_deleted = 1 WHERE file_hash = ?",
                (f.get('file_hash'),)
            )
            conn.commit()
            # Don't close - using thread-local connections

            app.logger.info(f"Cleaned up deleted file: {f.get('filename')}")
        except Exception as e:
            app.logger.error(f"Error cleaning up file {f.get('filename')}: {e}")


# ============ Main Routes ============

@app.route("/")
def index():
    """Serve Vue.js single-page application."""
    authorized_file = Path.home() / '.gnome' / 'authorized'

    if not authorized_file.exists():
        return render_template("welcome.html")

    return render_template("index.html")


@app.route("/api/authorize", methods=["POST"])
def api_authorize():
    """Mark user as having authorized file access."""
    try:
        authorized_file = Path.home() / '.gnome' / 'authorized'
        authorized_file.parent.mkdir(parents=True, exist_ok=True)
        authorized_file.write_text('authorized')

        app.logger.info("User authorized file access")
        return jsonify({"message": "Authorization saved"}), 200
    except Exception as exc:
        app.logger.error(f"Failed to save authorization: {exc}")
        return jsonify({"error": str(exc)}), 500


# ============ File & Search APIs ============

@app.route("/api/files")
def api_files():
    """Get list of all indexed files from all sources."""
    try:
        db_files = SYNC_MANAGER.get_all_files()

        files = []
        deleted_files = []

        for f in db_files:
            # For local sources, verify file still exists
            if f['source'] == 'Finder':
                file_path = f.get('file_path', '')
                if file_path and not os.path.exists(file_path):
                    # Mark for cleanup
                    deleted_files.append(f)
                    continue

            metadata = f.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            files.append({
                "name": f['filename'],
                "uploadDate": f.get('indexed_at'),
                "source": f['source'],
                "size": f.get('file_size'),
                "cloudUrl": metadata.get('webUrl') or metadata.get('webViewLink'),
                "indexed": True
            })

        # Clean up deleted files in the background
        if deleted_files:
            app.logger.info(f"Found {len(deleted_files)} deleted files, cleaning up...")
            threading.Thread(
                target=lambda: _cleanup_deleted_files(deleted_files),
                daemon=True
            ).start()

        # Get sync status for all sources
        sync_status = SYNC_MANAGER.get_all_status()

        files.sort(key=lambda x: x.get("uploadDate") or "", reverse=True)
        return jsonify({
            "files": files,
            "syncStatus": sync_status
        })
    except Exception as e:
        app.logger.error(f"Failed to fetch files: {e}")
        return jsonify({"files": [], "syncStatus": {}})


@app.route("/api/search", methods=["POST"])
def api_search():
    """Semantic search across all indexed sources."""
    data = request.get_json()
    query = data.get("query", "").strip() if data else ""
    top_k = data.get("top_k", 15) if data else 15
    source_filter = data.get("source") if data else None

    if not query:
        return jsonify({"error": "Please enter a query."}), 400

    try:
        # Get all files for metadata lookup
        db_files = SYNC_MANAGER.get_all_files()
        db_files_dict = {f.get('pinecone_id') or f.get('file_hash'): f for f in db_files}

        # Search via Voyage + Pinecone
        matches = SEARCH_ENGINE.search(
            query=query,
            top_k=top_k * 3,  # Get more for reranking
            source_filter=source_filter,
            use_reranking=True
        )

        # Format results
        results = []
        query_lower = query.lower()
        query_words = set(re.findall(r'\w+', query_lower))

        for match in matches:
            match_id = match.get("id", "")
            metadata = match.get("metadata", {})

            # Try to get file from database
            db_file = db_files_dict.get(match_id)

            # Skip files not in database (likely deleted)
            # For local sources like Finder, we require database presence
            source = metadata.get("source", "")
            if not db_file and source == 'Finder':
                continue  # File was deleted, skip it

            if db_file:
                db_metadata = db_file.get('metadata', {})
                if isinstance(db_metadata, str):
                    try:
                        db_metadata = json.loads(db_metadata)
                    except:
                        db_metadata = {}

                cloud_url = db_metadata.get('webUrl') or db_metadata.get('webViewLink')
                if not cloud_url and db_file['source'] == 'Google Drive':
                    cloud_url = f"https://drive.google.com/file/d/{db_file['file_path']}/view"

                result = {
                    "name": db_file['filename'],
                    "similarity": match.get("score", 0),
                    "source": db_file['source'],
                    "cloudUrl": cloud_url,
                    "file_path": db_file['file_path'],
                    "uploadDate": db_file.get('indexed_at'),
                    "indexed": True,
                    "type": db_metadata.get('type', 'file')
                }
            else:
                result = {
                    "name": metadata.get("filename", match_id),
                    "similarity": match.get("score", 0),
                    "source": metadata.get("source", "Unknown"),
                    "cloudUrl": metadata.get('webUrl'),
                    "file_path": metadata.get('file_path'),
                    "uploadDate": None,
                    "indexed": True,
                    "type": metadata.get('type', 'file')
                }

            # Boost filename matches
            filename_lower = result["name"].lower()
            filename_words = set(re.findall(r'\w+', filename_lower))
            if query_lower in filename_lower or query_words.issubset(filename_words):
                result["similarity"] = min(1.0, result["similarity"] + 0.3)

            results.append(result)

        # Sort by similarity and return top results
        results.sort(key=lambda x: x["similarity"], reverse=True)
        results = results[:top_k]

        app.logger.info(f"Search '{query}': {len(results)} results")
        if results:
            app.logger.info(f"  Top: {results[0]['name']} ({results[0]['similarity']:.3f})")

        return jsonify({"results": results}), 200

    except Exception as exc:
        app.logger.error("Search failed:\n%s", traceback.format_exc())
        return jsonify({"error": f"Search failed: {exc}"}), 500


# ============ Sync APIs ============

@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Trigger manual sync."""
    try:
        data = request.get_json(silent=True) or {}
        source = data.get("source")

        if source:
            result = SYNC_MANAGER.sync_source(source)
            return jsonify({"message": f"Synced {source}", "result": result}), 200
        else:
            results = SYNC_MANAGER.sync_all()
            return jsonify({"message": "Synced all sources", "results": results}), 200
    except Exception as exc:
        app.logger.error(f"Sync failed: {exc}")
        app.logger.error(traceback.format_exc())
        return jsonify({"error": f"Sync failed: {str(exc)}"}), 500


@app.route("/api/sync/status")
def api_sync_status():
    """Get sync status for all sources."""
    try:
        status = SYNC_MANAGER.get_all_status()
        return jsonify({"status": status}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/clear-finder", methods=["POST"])
def api_clear_finder():
    """
    Clear Finder index and re-sync with fresh data.
    Use this to reset the Finder index if files from wrong folders are showing.
    """
    try:
        from database.models import clear_source_files

        # Clear all Finder files from database
        deleted_count = clear_source_files('Finder')
        app.logger.info(f"Cleared {deleted_count} Finder files from database")

        # Also try to delete from Pinecone
        if SEARCH_ENGINE:
            try:
                SEARCH_ENGINE.delete_source('Finder')
                app.logger.info("Deleted Finder vectors from Pinecone")
            except Exception as e:
                app.logger.warning(f"Could not delete from Pinecone: {e}")

        # Trigger fresh sync in background
        def resync_finder():
            try:
                result = SYNC_MANAGER.sync_source('Finder', max_files=500)
                app.logger.info(f"Finder re-sync complete: {result}")
            except Exception as e:
                app.logger.error(f"Finder re-sync failed: {e}")

        threading.Thread(target=resync_finder, daemon=True).start()

        return jsonify({
            "message": f"Cleared {deleted_count} files, re-syncing Finder...",
            "deleted_count": deleted_count
        }), 200

    except Exception as exc:
        app.logger.error(f"Failed to clear Finder: {exc}")
        app.logger.error(traceback.format_exc())
        return jsonify({"error": str(exc)}), 500


@app.route("/api/sources")
def api_sources():
    """Get all available sources with their status."""
    try:
        status = SYNC_MANAGER.get_all_status()

        sources = []
        for name, info in status.items():
            sources.append({
                "name": name,
                "connected": info.get("connected", False),
                "file_count": info.get("file_count", 0),
                "last_sync": info.get("last_sync"),
                "status": info.get("status", "idle"),
                "requires_oauth": info.get("requires_oauth", False),
                "requires_fda": info.get("requires_fda", False),
                "category": info.get("category", "local"),
                "error": info.get("error")
            })

        return jsonify({"sources": sources}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/stats")
def api_stats():
    """Get index statistics."""
    try:
        stats = SEARCH_ENGINE.get_stats()
        return jsonify(stats), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ============ Connection APIs ============

@app.route("/api/connect/google-drive", methods=["POST"])
def api_connect_gdrive():
    """Connect Google Drive - opens browser for OAuth via proxy."""
    try:
        # OAuth is handled by proxy server, just open the auth URL
        success = SYNC_MANAGER.connect_google_drive()

        if success:
            return jsonify({"message": "Google Drive connected! Syncing files..."}), 200
        else:
            # OAuth flow started - browser opened
            return jsonify({
                "message": "Opening Google Drive authorization in browser...",
                "pending_oauth": True
            }), 200

    except Exception as exc:
        app.logger.error(f"Google Drive connection failed: {exc}")

        if "access_denied" in str(exc).lower():
            return jsonify({
                "error": "Access denied - Please allow Gnome to access your Google Drive",
                "code": "access_denied"
            }), 403

        return jsonify({"error": f"Connection error: {str(exc)}"}), 500


@app.route("/api/connect/gmail", methods=["POST"])
def api_connect_gmail():
    """Connect Gmail - opens browser for OAuth via proxy."""
    try:
        success = SYNC_MANAGER.connect_gmail()

        if success:
            return jsonify({"message": "Gmail connected! Indexing emails..."}), 200
        else:
            # OAuth flow started - browser opened
            return jsonify({
                "message": "Opening Gmail authorization in browser...",
                "pending_oauth": True
            }), 200

    except Exception as exc:
        app.logger.error(f"Gmail connection failed: {exc}")
        return jsonify({"error": f"Connection error: {str(exc)}"}), 500


@app.route("/api/connect/onedrive", methods=["POST"])
def api_connect_onedrive():
    """Connect OneDrive - opens browser for OAuth via proxy."""
    try:
        engine = SYNC_MANAGER.engines['OneDrive']
        auth_url = engine.get_auth_url()

        # Open the browser for OAuth
        app.logger.info(f"Opening OneDrive OAuth URL in browser...")
        webbrowser.open(auth_url, new=2, autoraise=True)

        return jsonify({
            "message": "Opening OneDrive authorization in browser...",
            "auth_url": auth_url,
            "pending_oauth": True
        }), 200

    except Exception as exc:
        app.logger.error(f"OneDrive connection failed: {exc}")
        return jsonify({"error": f"Connection error: {str(exc)}"}), 500


@app.route("/api/connect/outlook", methods=["POST"])
def api_connect_outlook():
    """Connect Outlook - opens browser for OAuth via proxy."""
    try:
        engine = SYNC_MANAGER.engines['Outlook']
        auth_url = engine.get_auth_url()

        # Open the browser for OAuth
        app.logger.info(f"Opening Outlook OAuth URL in browser...")
        webbrowser.open(auth_url, new=2, autoraise=True)

        return jsonify({
            "message": "Opening Outlook authorization in browser...",
            "auth_url": auth_url,
            "pending_oauth": True
        }), 200

    except Exception as exc:
        app.logger.error(f"Outlook connection failed: {exc}")
        return jsonify({"error": f"Connection error: {str(exc)}"}), 500


@app.route("/api/oauth/callback", methods=["GET"])
def api_oauth_callback():
    """
    Unified OAuth callback handler.
    Receives tokens from proxy server after OAuth flow completes.
    The proxy exchanges the auth code for tokens, then redirects here with the tokens.
    """
    # Get tokens and state from query params
    access_token = request.args.get("access_token")
    refresh_token = request.args.get("refresh_token")
    expires_in = request.args.get("expires_in", "3600")
    email = request.args.get("email", "")
    state = request.args.get("state", "")  # e.g., "google_drive", "gmail", "outlook", "onedrive"
    error = request.args.get("error")

    if error:
        app.logger.error(f"OAuth error: {error}")
        return render_template("oauth_error.html", error=error)

    if not access_token:
        return render_template("oauth_error.html", error="No access token received")

    # Build tokens dict
    tokens = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_in': expires_in,
        'email': email
    }

    try:
        # Route to appropriate handler based on state
        if state == "google_drive":
            engine = SYNC_MANAGER.engines.get('Google Drive')
            if engine and hasattr(engine, 'complete_oauth'):
                success = engine.complete_oauth(tokens)
                service_name = "Google Drive"
            else:
                return render_template("oauth_error.html", error="Google Drive engine not found")

        elif state == "gmail":
            engine = SYNC_MANAGER.engines.get('Gmail')
            if engine and hasattr(engine, 'complete_oauth'):
                success = engine.complete_oauth(tokens)
                service_name = "Gmail"
            else:
                return render_template("oauth_error.html", error="Gmail engine not found")

        elif state == "outlook":
            engine = SYNC_MANAGER.engines.get('Outlook')
            if engine and hasattr(engine, 'complete_oauth'):
                success = engine.complete_oauth(tokens)
                service_name = "Outlook"
            else:
                return render_template("oauth_error.html", error="Outlook engine not found")

        elif state == "onedrive":
            engine = SYNC_MANAGER.engines.get('OneDrive')
            if engine and hasattr(engine, 'complete_oauth'):
                success = engine.complete_oauth(tokens)
                service_name = "OneDrive"
            else:
                return render_template("oauth_error.html", error="OneDrive engine not found")

        else:
            return render_template("oauth_error.html", error=f"Unknown OAuth state: {state}")

        if success:
            app.logger.info(f"{service_name} OAuth completed successfully for {email}")

            # Spawn sync thread after successful OAuth
            # Uses module-level function to avoid closure issues with daemon threads
            import threading

            max_files = 100 if service_name in ['Gmail', 'Outlook'] else 50
            sync_thread = threading.Thread(
                target=_run_initial_sync_thread,
                args=(service_name, max_files),
                daemon=True
            )
            sync_thread.start()
            app.logger.info(f"Spawned initial {service_name} sync thread (thread_id={sync_thread.ident})...")

            return render_template("oauth_success.html", service=service_name)
        else:
            return render_template("oauth_error.html", error=f"Failed to complete {service_name} authorization")

    except Exception as exc:
        app.logger.error(f"OAuth callback failed: {exc}")
        import traceback
        app.logger.error(traceback.format_exc())
        return render_template("oauth_error.html", error=str(exc))


@app.route("/api/oauth/microsoft/callback", methods=["GET"])
def api_microsoft_oauth_callback():
    """
    Legacy Microsoft OAuth callback - redirects to unified callback.
    Kept for backwards compatibility.
    """
    # Just redirect to the unified callback
    return api_oauth_callback()


@app.route("/api/disconnect/<source>", methods=["POST"])
def api_disconnect(source):
    """Disconnect a source."""
    try:
        success = SYNC_MANAGER.disconnect_source(source)
        if success:
            return jsonify({"message": f"{source} disconnected"}), 200
        else:
            return jsonify({"error": f"Cannot disconnect {source}"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ============ File Operations ============

@app.route("/api/open-file/<filename>")
def api_open_file(filename):
    """Open a file in appropriate app."""
    try:
        source = request.args.get('source')
        files = SYNC_MANAGER.get_all_files()

        if source:
            file_info = next((f for f in files if f['filename'] == filename and f['source'] == source), None)
        else:
            file_info = next((f for f in files if f['filename'] == filename), None)

        if not file_info:
            return jsonify({"error": "File not found"}), 404

        source_name = file_info['source']

        # Local files: return the path for frontend/Electron to open
        # This avoids macOS sandbox permission issues
        if source_name == 'Finder':
            file_path = file_info['file_path']

            # Check if file still exists
            if not os.path.exists(file_path):
                # File was deleted - mark it in database and trigger cleanup
                app.logger.warning(f"File no longer exists: {file_path}")
                # Clean up this file
                threading.Thread(
                    target=lambda: _cleanup_deleted_files([file_info]),
                    daemon=True
                ).start()
                return jsonify({
                    "error": "File no longer exists. It may have been moved or deleted.",
                    "code": "file_not_found"
                }), 404

            # Return the file path - let Electron/frontend open it
            # This works better with macOS sandbox permissions
            return jsonify({
                "message": "File found",
                "file_path": file_path,
                "open_locally": True
            }), 200

        # Cloud files: open in browser
        elif source_name in ['Google Drive', 'OneDrive']:
            metadata = file_info.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            url = metadata.get('webUrl') or metadata.get('webViewLink')
            if not url and source_name == 'Google Drive':
                url = f"https://drive.google.com/file/d/{file_info['file_path']}/view"

            if url:
                webbrowser.open(url, new=2, autoraise=True)
                return jsonify({"message": "File opened in browser"}), 200
            else:
                return jsonify({"error": "No URL available"}), 400

        # Email attachments: open the parent email in web client
        elif source_name in ['Gmail', 'Outlook']:
            metadata = file_info.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            if source_name == 'Gmail':
                # Open the email thread in Gmail using the correct account
                gmail_message_id = metadata.get('gmail_message_id', '')
                account_email = metadata.get('account_email', '')

                if gmail_message_id:
                    # Use authuser param with email to open correct account
                    if account_email:
                        from urllib.parse import quote
                        url = f"https://mail.google.com/mail/u/?authuser={quote(account_email)}#inbox/{gmail_message_id}"
                    else:
                        url = f"https://mail.google.com/mail/u/0/#inbox/{gmail_message_id}"
                    webbrowser.open(url, new=2, autoraise=True)
                    return jsonify({"message": "Email opened in Gmail"}), 200
                else:
                    return jsonify({"error": "No Gmail message ID found"}), 400

            elif source_name == 'Outlook':
                # Open the email in Outlook web using the correct account
                outlook_message_id = metadata.get('outlook_message_id', '')
                account_email = metadata.get('account_email', '')

                if outlook_message_id:
                    # Outlook uses email in the URL path
                    if account_email:
                        from urllib.parse import quote
                        url = f"https://outlook.live.com/mail/{quote(account_email)}/inbox/id/{outlook_message_id}"
                    else:
                        url = f"https://outlook.live.com/mail/0/inbox/id/{outlook_message_id}"
                    webbrowser.open(url, new=2, autoraise=True)
                    return jsonify({"message": "Email opened in Outlook"}), 200
                else:
                    return jsonify({"error": "No Outlook message ID found"}), 400

        else:
            return jsonify({"error": f"Cannot open files from {source_name}"}), 400

    except Exception as exc:
        app.logger.error(f"Failed to open file: {exc}")
        return jsonify({"error": str(exc)}), 500


# ============ Utility APIs ============

@app.route("/api/discover", methods=["POST"])
def api_discover():
    """Quick file discovery - count files without indexing."""
    data = request.get_json() or {}
    source = data.get("source", "Finder")

    try:
        if source in SYNC_MANAGER.engines:
            engine = SYNC_MANAGER.engines[source]
            files = engine.fetch_files()
            return jsonify({
                "source": source,
                "total_files": len(files),
                "indexed": len(SYNC_MANAGER.get_files_by_source(source))
            }), 200
        else:
            return jsonify({"error": f"Unknown source: {source}"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/debug/env")
def api_debug_env():
    """Debug endpoint - show configuration status."""
    return jsonify({
        "mode": "MVP - Proxy Architecture",
        "embeddings": "Voyage AI via proxy (voyage-3, 1024-dim)",
        "vector_db": "Pinecone via proxy (serverless)",
        "proxy_url": PROXY_URL,
        "sources": list(SYNC_MANAGER.engines.keys()),
        "google_oauth": "baked in (via proxy)",
        "microsoft_oauth": "baked in (via proxy)",
        "voyage_api": "direct" if os.environ.get('VOYAGE_API_KEY') else "via proxy",
        "pinecone_api": "direct" if os.environ.get('PINECONE_API_KEY') else "via proxy"
    })


@app.route("/api/request-integration", methods=["POST"])
def api_request_integration():
    """Handle user request for new integration."""
    try:
        data = request.get_json()
        app_name = data.get('app_name', 'Not specified')

        sender_email = os.environ.get('GMAIL_USER')
        sender_password = os.environ.get('GMAIL_APP_PASSWORD')

        if not sender_password:
            app.logger.warning("No Gmail password configured - skipping email")
            return jsonify({"message": "Request received"}), 200

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = "kennethfrisard05@gmail.com"
        msg['Subject'] = f"New Integration Request: {app_name}"

        body = f"""
        New integration request for Gnome!

        Requested App: {app_name}
        Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        Hostname: {socket.gethostname()}

        User wants to connect {app_name} to Gnome.
        """

        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        app.logger.info(f"Integration request sent for: {app_name}")
        return jsonify({"message": "Integration request sent"}), 200
    except Exception as exc:
        app.logger.error(f"Failed to send integration request: {exc}")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    debug_mode = '--debug' in sys.argv

    try:
        app.run(debug=debug_mode, host="0.0.0.0", port=5001)
    finally:
        SYNC_MANAGER.stop_auto_sync()
        DB.close()
