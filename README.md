# 🏡 Gnome - AI-Powered Semantic PDF Search

> Find anything in your PDFs, instantly. Search by meaning, not just keywords.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)

## 🎯 What is Gnome?

Gnome is a native desktop application that lets you search through your PDF documents using natural language. Instead of exact keyword matching, Gnome understands the *meaning* of your query using AI-powered semantic search.

**Example searches:**
- "tax documents" → finds 1040 forms, W-2s, receipts
- "physics homework" → finds problem sets, lab reports  
- "resume" → finds CVs, cover letters, portfolios

## ✨ Features

- 🔍 **Semantic Search**: Find documents by meaning, not just keywords
- 🤖 **AI-Powered**: Uses Voyage AI's multimodal embeddings
- ⚡ **Lightning Fast**: Powered by Pinecone vector database
- 🎨 **Beautiful UI**: Clean, modern interface inspired by macOS Finder
- 🔒 **Privacy First**: Your data stays on your machine
- 📦 **Native Desktop App**: Built with Electron, runs offline after setup
- 🆓 **No Subscription**: Bring your own API keys

## 🚀 Quick Start

### Download
Visit [gnom3.com](https://gnom3.com) or download directly:
- [macOS (Apple Silicon)](https://github.com/veselyo/gnome/releases/latest/download/Gnome-1.0.0-arm64.dmg)
- [macOS (Intel)](https://github.com/veselyo/gnome/releases/latest/download/Gnome-1.0.0-x64.dmg)

### Installation
1. Open `Gnome-1.0.0.dmg`
2. Drag Gnome to Applications
3. **Right-click** Gnome.app → Open (first time only)
4. Enter your API keys (see below)

### API Keys Required
You'll need:
1. **Voyage AI API Key**: [Get one here](https://www.voyageai.com/)
2. **Pinecone API Key**: [Get one here](https://www.pinecone.io/)
3. **Pinecone Host URL**: From your Pinecone dashboard

Both services offer free tiers!

## 📚 Documentation

- [Installation Guide](INSTALLATION.md) - Detailed setup instructions
- [Deployment Guide](DEPLOYMENT.md) - How to build and deploy
- [Contributing](CONTRIBUTING.md) - How to contribute

## 🏗️ Architecture

```
Gnome Desktop App
├── Electron Shell (UI)
│   ├── Vue.js 3 Frontend
│   └── Native macOS Integration
├── Flask Backend (Python)
│   ├── PDF Parsing (PyMuPDF)
│   ├── Embedding Generation (Voyage AI)
│   └── Vector Search (Pinecone)
└── Local File Storage
```

## 🛠️ Development

### Prerequisites
- macOS 11.0+
- Node.js 18+
- Python 3.9+
- Voyage AI API key
- Pinecone API key

### Setup
```bash
# Clone the repo
git clone https://github.com/veselyo/gnome.git
cd gnome

# Install Python dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Electron dependencies
cd electron
npm install

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys

# Run in development
npm start
```

### Build
```bash
cd electron
npm run build
```

Output: `electron/dist/Gnome-1.0.0.dmg`

## 🧪 Tech Stack

**Frontend:**
- Electron 28
- Vue.js 3
- Vanilla CSS

**Backend:**
- Python 3.9
- Flask 3.1
- PyMuPDF (PDF parsing)
- Pillow (image processing)

**AI & Vector DB:**
- Voyage AI (multimodal-3 embeddings)
- Pinecone (vector database)

## 📁 Project Structure

```
gnome/
├── demo/                    # Flask backend
│   ├── app.py              # Main Flask application
│   ├── templates/          # HTML templates (Vue.js)
│   ├── static/             # Static assets (icons, logos)
│   └── uploads/            # PDF storage (sample files)
├── semantic_search/         # Core search logic
│   ├── parsing_engine.py   # PDF → Images
│   ├── embedding_engine.py # Images → Vectors (Voyage AI)
│   └── vector_database.py  # Vector storage/search (Pinecone)
├── electron/               # Desktop app wrapper
│   ├── main.js            # Electron main process
│   ├── preload.js         # Security layer
│   └── package.json       # Build configuration
├── requirements.txt        # Python dependencies
├── Makefile               # Build commands
└── README.md              # This file
```

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 Roadmap

### v1.0.0 (Current - MVP)
- ✅ macOS desktop app
- ✅ Semantic PDF search
- ✅ Basic UI
- ✅ Manual API key setup

### v1.1.0 (Planned)
- [ ] Windows support
- [ ] Auto-update functionality
- [ ] Settings persistence
- [ ] Multiple file formats (DOCX, TXT, etc.)

### v1.2.0 (Future)
- [ ] Cloud sync
- [ ] Team collaboration
- [ ] Mobile app
- [ ] OCR for scanned documents
- [ ] Chrome extension

## 🐛 Known Issues

- App requires manual "Open" on first launch (unsigned)
- Port 5001 conflicts with AirPlay Receiver on macOS
- Large PDFs (>50MB) take time to process
- Requires internet for initial setup

See [Issues](https://github.com/veselyo/gnome/issues) for full list.

## 💰 Cost

**MVP (what you need):**
- Gnome: Free and open source
- Voyage AI: $0-5/month (free tier available)
- Pinecone: $0-10/month (free tier available)

**Total**: ~$0-15/month depending on usage

## 🔒 Privacy & Security

- Your PDFs stay on your local machine
- Embeddings stored in your Pinecone account
- No Gnome servers (we don't track anything!)
- You control your API keys and data
- Open source - audit the code yourself

## 📄 License

MIT License - see [LICENSE](LICENSE) file

## 👨‍💻 Author

**Kenneth Frisard**
- GitHub: [@kennethfrisard05](https://github.com/kennethfrisard05)
- Original concept by: [@veselyo](https://github.com/veselyo)

## 🙏 Acknowledgments

- [Voyage AI](https://www.voyageai.com/) for multimodal embeddings
- [Pinecone](https://www.pinecone.io/) for vector database
- [Electron](https://www.electronjs.org/) for desktop framework
- [Flask](https://flask.palletsprojects.com/) for backend

## 📞 Support

- 🐛 Bug reports: [GitHub Issues](https://github.com/veselyo/gnome/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/veselyo/gnome/discussions)
- 📧 Email: support@gnom3.com

---

**Built with ❤️ for better document search**

Star ⭐ this repo if you find it helpful!
