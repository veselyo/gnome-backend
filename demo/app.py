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
import os

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
from semantic_search.hybrid_search import hybrid_search_rerank, boost_exact_matches, filter_by_relevance
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
    """API endpoint for hybrid semantic + keyword search across all sources."""
    data = request.get_json()
    query = data.get("query", "").strip() if data else ""
    top_k = data.get("top_k", 30) if data else 30  # Get more results for reranking

    if not query:
        return jsonify({"error": "Please enter a query."}), 400

    try:
        # Step 1: Semantic search via Pinecone
        response = semantic_search(
            query, PINECONE_IDX, VOYAGE_CLIENT, top_k, NAMESPACE
        )
        matches = response.get("matches", [])

        # Get all files from database for matching
        db_files = SYNC_MANAGER.get_all_files()
        db_files_dict = {f['pinecone_id']: f for f in db_files}
        
        # Format results with metadata from Pinecone + Database
        results = []
        for match in matches:
            match_id = match.get("id", "")
            metadata = match.get("metadata", {})
            
            # Try to get file from database by pinecone_id
            db_file = db_files_dict.get(match_id)
            
            if db_file:
                # Use database info (most reliable)
                result = {
                    "name": db_file['filename'],
                    "similarity": match.get("score", 0),
                    "source": db_file['source'],
                    "cloudUrl": db_file.get('metadata', {}).get('webUrl') if isinstance(db_file.get('metadata'), dict) else None,
                    "file_path": db_file['file_path'],
                    "uploadDate": db_file.get('indexed_at'),
                    "indexed": True
                }
            else:
                # Fallback to Pinecone metadata
                result = {
                    "name": metadata.get("filename", match_id),
                    "similarity": match.get("score", 0),
                    "source": metadata.get("source", "Unknown"),
                    "cloudUrl": metadata.get('webUrl'),
                    "file_path": metadata.get('file_path'),
                    "uploadDate": None,
                    "indexed": True
                }
            
            results.append(result)
        
        # Step 2: Apply hybrid search reranking (semantic + keyword)
        results = hybrid_search_rerank(query, results, semantic_weight=0.6, keyword_weight=0.4)
        
        # Step 3: Boost exact matches in filename
        results = boost_exact_matches(query, results, boost_factor=0.3)
        
        # Step 4: Filter low-relevance results (lower threshold)
        results = filter_by_relevance(results, min_score=0.1)
        
        # Step 5: Return top 10 after reranking
        results = results[:10]

        app.logger.info(f"Search '{query}': {len(results)} results (from {len(matches)} semantic matches)")
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
    """Get sync status and file counts for all sources."""
    try:
        status = SYNC_MANAGER.get_sync_status()
        
        # Add file counts per source
        for source in ['Finder', 'Google Drive', 'OneDrive']:
            indexed_count = len(SYNC_MANAGER.get_files_by_source(source))
            if source in status:
                status[source]['indexed_count'] = indexed_count
        
        return jsonify({"status": status}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/discover", methods=["POST"])
def api_discover():
    """Quick file discovery - just count files without indexing."""
    data = request.get_json() or {}
    source = data.get("source", "Finder")
    
    try:
        if source == "Finder":
            engine = SYNC_MANAGER.engines['Finder']
            files = engine.fetch_files()
            return jsonify({
                "source": source,
                "total_files": len(files),
                "indexed": len(SYNC_MANAGER.get_files_by_source(source))
            }), 200
        else:
            return jsonify({"error": "Discovery only supported for Finder"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/connect/google-drive", methods=["POST"])
def api_connect_gdrive():
    """Initiate Google Drive OAuth connection."""
    try:
        # Check if OAuth is configured
        if not os.environ.get('GOOGLE_CLIENT_ID') or not os.environ.get('GOOGLE_CLIENT_SECRET'):
            return jsonify({
                "error": "Google Drive OAuth not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file. See OAUTH-SETUP.md for instructions."
            }), 400
        
        success = SYNC_MANAGER.connect_google_drive()
        if success:
            return jsonify({"message": "Google Drive connected successfully! Syncing files..."}), 200
        else:
            return jsonify({"error": "Failed to connect Google Drive. Check logs for details."}), 500
    except Exception as exc:
        app.logger.error(f"Google Drive connection failed: {exc}")
        return jsonify({"error": f"Connection error: {str(exc)}"}), 500


@app.route("/api/connect/onedrive", methods=["POST"])
def api_connect_onedrive():
    """Initiate OneDrive OAuth connection."""
    try:
        # Check if OAuth is configured
        if not os.environ.get('MICROSOFT_CLIENT_ID') or not os.environ.get('MICROSOFT_CLIENT_SECRET'):
            return jsonify({
                "error": "OneDrive OAuth not configured. Please set MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET in your .env file. See OAUTH-SETUP.md for instructions."
            }), 400
        
        success = SYNC_MANAGER.connect_onedrive()
        if success:
            return jsonify({"message": "OneDrive connected successfully! Syncing files..."}), 200
        else:
            return jsonify({"error": "Failed to connect OneDrive. Check logs for details."}), 500
    except Exception as exc:
        app.logger.error(f"OneDrive connection failed: {exc}")
        return jsonify({"error": f"Connection error: {str(exc)}"}), 500


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