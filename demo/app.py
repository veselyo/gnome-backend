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


@app.route("/")
def index():
    """Serve Vue.js single-page application."""
    return render_template("index.html")


@app.route("/api/files")
def api_files():
    """API endpoint to get list of uploaded files."""
    files = [
        {"name": f.name, "uploadDate": f.stat().st_mtime * 1000}
        for f in UPLOAD_FOLDER.glob("*.pdf")
    ]
    files.sort(key=lambda x: x["uploadDate"], reverse=True)
    return jsonify({"files": files})


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


if __name__ == "__main__":
    # Disable debug mode when running from Electron to avoid restart issues
    import sys
    debug_mode = '--debug' in sys.argv
    app.run(debug=debug_mode, host="0.0.0.0", port=5001)