from pathlib import Path
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
)
import traceback
import sys
import secrets

# Ensure semantic_search package is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from semantic_search.parsing_engine import parse_local_pdf
from semantic_search.embedding_engine import init_voyage, embed_pdf
from semantic_search.vector_database import (
    init_pinecone_idx,
    store_embeddings,
    semantic_search,
)
from semantic_search.file_processor import process_file, is_supported_file
from database.models import GnomeDatabase
from sync_engine.sync_manager import SyncManager
import subprocess

# Flask setup
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = (
    Path(__file__).resolve().parent / "uploads"
)
app.secret_key = secrets.token_hex(16)

UPLOAD_FOLDER: Path = app.config["UPLOAD_FOLDER"]
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# Initialize external clients once
VOYAGE_CLIENT = init_voyage()
PINECONE_IDX = init_pinecone_idx()
NAMESPACE = "demo"

# Initialize database and sync manager
DB = GnomeDatabase()
SYNC_MANAGER = SyncManager(DB, VOYAGE_CLIENT, PINECONE_IDX, NAMESPACE)

# Start auto-sync in background
SYNC_MANAGER.start_auto_sync()


@app.route("/")
def index():
    """Serve Vue.js single-page application."""
    return render_template("index.html")


@app.route("/api/files")
def api_files():
    """API endpoint to get list of all files (indexed + pending) from all sources."""
    try:
        # Get indexed files from database
        db_files = SYNC_MANAGER.get_all_files()
        
        files = []
        for f in db_files:
            files.append({
                "name": f['filename'],
                "uploadDate": f.get('indexed_at'),
                "source": f['source'],
                "size": f.get('file_size'),
                "cloudUrl": f.get('metadata', {}).get('webUrl') if isinstance(f.get('metadata'), dict) else None,
                "indexed": True
            })
        
        # Also get sync status to show pending count
        sync_status = SYNC_MANAGER.get_sync_status()
        
        files.sort(key=lambda x: x.get("uploadDate", ""), reverse=True)
        return jsonify({
            "files": files,
            "syncStatus": sync_status
        })
    except Exception as e:
        app.logger.error(f"Failed to fetch files: {e}")
        return jsonify({"files": [], "syncStatus": {}})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """API endpoint to handle PDF upload and pipeline processing."""
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    save_path = UPLOAD_FOLDER / file.filename
    file.save(save_path)

    try:
        # Parse PDF into images
        images = parse_local_pdf(str(save_path))
        # Embed images
        embedding = embed_pdf(images, VOYAGE_CLIENT)
        # Store embeddings in Pinecone
        store_embeddings(file.filename, PINECONE_IDX, embedding, NAMESPACE)
        return jsonify({"message": f"Successfully uploaded and indexed {file.filename}"}), 200
    except Exception as exc:  # pylint: disable=broad-except
        save_path.unlink(missing_ok=True)
        app.logger.error("Upload failed:\n%s", traceback.format_exc())
        return jsonify({"error": f"Failed to process file: {exc}"}), 500


@app.route("/api/search", methods=["POST"])
def api_search():
    """API endpoint for semantic search."""
    data = request.get_json()
    query = data.get("query", "").strip() if data else ""
    top_k = data.get("top_k", 5) if data else 5

    if not query:
        return jsonify({"error": "Please enter a query."}), 400

    try:
        response = semantic_search(
            query, PINECONE_IDX, VOYAGE_CLIENT, top_k, NAMESPACE
        )
        # Pinecone returns dict with "matches"
        matches = response.get("matches", [])

        # Format results for frontend
        results = [
            {
                "name": match.get("id", "Unknown"),
                "similarity": match.get("score", 0),
                "uploadDate": None  # Can be enhanced later
            }
            for match in matches
        ]

        return jsonify({"results": results}), 200
    except Exception as exc:  # pylint: disable=broad-except
        app.logger.error("Search failed:\n%s", traceback.format_exc())
        return jsonify({"error": f"Search failed: {exc}"}), 500


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """API endpoint to trigger manual sync."""
    data = request.get_json() or {}
    source = data.get("source")  # Optional: sync specific source
    
    try:
        if source:
            result = SYNC_MANAGER.sync_source(source)
            return jsonify({"message": f"Synced {source}", "result": result}), 200
        else:
            results = SYNC_MANAGER.sync_all()
            return jsonify({"message": "Synced all sources", "results": results}), 200
    except Exception as exc:
        app.logger.error(f"Sync failed: {exc}")
        return jsonify({"error": f"Sync failed: {exc}"}), 500


@app.route("/api/sync/status")
def api_sync_status():
    """Get sync status for all sources."""
    try:
        status = SYNC_MANAGER.get_sync_status()
        return jsonify({"status": status}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/connect/google-drive", methods=["POST"])
def api_connect_gdrive():
    """Initiate Google Drive OAuth connection."""
    try:
        success = SYNC_MANAGER.connect_google_drive()
        if success:
            return jsonify({"message": "Google Drive connected successfully"}), 200
        else:
            return jsonify({"error": "Failed to connect Google Drive"}), 500
    except Exception as exc:
        app.logger.error(f"Google Drive connection failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/connect/onedrive", methods=["POST"])
def api_connect_onedrive():
    """Initiate OneDrive OAuth connection."""
    try:
        success = SYNC_MANAGER.connect_onedrive()
        if success:
            return jsonify({"message": "OneDrive connected successfully"}), 200
        else:
            return jsonify({"error": "Failed to connect OneDrive"}), 500
    except Exception as exc:
        app.logger.error(f"OneDrive connection failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/disconnect/<source>", methods=["POST"])
def api_disconnect(source):
    """Disconnect a cloud source."""
    try:
        SYNC_MANAGER.disconnect_source(source)
        return jsonify({"message": f"{source} disconnected"}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/open-file/<filename>")
def api_open_file(filename):
    """Open a local file in Finder."""
    try:
        # Get file from database
        files = SYNC_MANAGER.get_all_files()
        file_info = next((f for f in files if f['filename'] == filename and f['source'] == 'Finder'), None)
        
        if not file_info:
            return jsonify({"error": "File not found"}), 404
        
        file_path = file_info['file_path']
        
        # Open file in default app (macOS)
        subprocess.run(['open', file_path], check=True)
        
        return jsonify({"message": "File opened"}), 200
    except Exception as exc:
        app.logger.error(f"Failed to open file: {exc}")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    # Disable debug mode when running from Electron to avoid restart issues
    import sys
    debug_mode = '--debug' in sys.argv
    
    try:
        app.run(debug=debug_mode, host="0.0.0.0", port=5001)
    finally:
        # Cleanup on shutdown
        SYNC_MANAGER.stop_auto_sync()
        DB.close()