# Gnome MVP - Semantic Search Desktop App

## Project Overview
Gnome is a macOS desktop app that provides semantic search across 6 data sources:
- **Local:** Finder, iCloud Drive
- **Cloud:** Google Drive, Gmail, OneDrive, Outlook

Architecture: Voyage AI (voyage-3 embeddings) + Pinecone (vector database) + Flask backend + Electron wrapper

## Development Environment

```bash
# Activate Python environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run Flask development server
python demo/app.py  # Runs on http://localhost:5001

# Run Electron app (production mode)
cd electron && npm start
```

## Environment Variables

Create `.env` in `electron/` for development or `~/.gnome-env` for production:
```
VOYAGE_API_KEY=your_key
PINECONE_API_KEY=your_key
PINECONE_HOST=your_host
GOOGLE_CLIENT_ID=your_id
GOOGLE_CLIENT_SECRET=your_secret
MICROSOFT_CLIENT_ID=your_id
MICROSOFT_CLIENT_SECRET=your_secret
```

## Code Architecture

```
gnome/
├── demo/                    # Flask web app
│   ├── app.py              # Main Flask routes
│   ├── templates/          # HTML (Vue.js SPA)
│   └── static/             # CSS, icons
├── sync_engine/            # Data source connectors
│   ├── sync_manager.py     # Orchestrates all 6 sources
│   ├── finder_sync.py      # Local file system
│   ├── icloud_drive_sync.py
│   ├── gdrive_sync.py      # Google Drive
│   ├── gmail_sync.py       # Gmail + attachments
│   ├── onedrive_sync.py    # OneDrive
│   └── outlook_sync.py     # Outlook
├── semantic_search/        # AI-powered search
│   ├── voyage_embeddings.py  # Voyage AI client
│   ├── pinecone_database.py  # Vector storage
│   └── search_engine.py      # Combined search logic
├── database/
│   └── models.py           # SQLite for metadata, OAuth tokens
└── electron/               # Desktop app wrapper
    ├── main.js             # Electron main process
    └── package.json        # Build config
```

## Key Patterns

- **Graceful degradation:** App works without API keys (limited mode)
- **OAuth flow:** Google/Microsoft auth via Flask callbacks
- **Namespace isolation:** Each user gets unique Pinecone namespace
- **Embedding cache:** `~/.gnome/embedding_cache/` avoids re-embedding

## Common Tasks

| Task | Command |
|------|---------|
| Run dev server | `python demo/app.py` |
| Run Electron | `cd electron && npm start` |
| Build Electron | `cd electron && npm run build` |
| Install deps | `pip install -r requirements.txt` |
| Kill Flask | `lsof -ti:5001 \| xargs kill -9` |

## Gotchas

- Pinecone package is `pinecone` not `pinecone-client` (v5+)
- Flask runs on port 5001 (not 5000) to avoid AirPlay conflict
- Apple Mail/Notes removed from MVP (require Full Disk Access)
- Electron loads `.env` from `electron/` in dev, `~/.gnome-env` in prod
