# Installing Gnome DMG

## Prerequisites

**Before installing the DMG, you need:**

1. **Python 3.9+** (comes with macOS)
2. **Install Python dependencies globally:**

```bash
pip3 install flask voyageai pinecone PyMuPDF Pillow python-dotenv
```

This installs the required packages that Gnome needs to run.

## Installation Steps

1. **Download the DMG** for your Mac type:
   - Apple Silicon (M1/M2/M3): `Gnome-1.0.0-arm64.dmg`
   - Intel Mac: `Gnome-1.0.0.dmg`

2. **Open the DMG** and drag Gnome to Applications

3. **Remove quarantine flag:**
```bash
xattr -cr /Applications/Gnome.app
```

4. **Set up API keys:**
Create `~/.gnome-env` file:
```bash
cat > ~/.gnome-env << 'EOF'
export VOYAGE_API_KEY="your_voyage_api_key_here"
export PINECONE_API_KEY="your_pinecone_api_key_here"
export PINECONE_HOST="your_pinecone_host_here"
EOF
```

5. **Launch Gnome** from Applications folder

## Alternative: Run from Source (Recommended for MVP)

For the MVP/testing, it's easier to run from source:

```bash
cd /Users/kennethfrisardiii/Downloads/gnome/electron
npm start
```

This uses the local venv and doesn't require global Python package installation.

## Why This is Needed

- The DMG uses system Python (not bundled venv)
- Bundling Python environments is complex and increases app size significantly
- For v1.0, we use system Python + global packages
- Future versions will bundle Python with PyInstaller

## Troubleshooting

**"Python3 not found":**
```bash
which python3
# Should show: /usr/bin/python3
```

**"Module not found":**
```bash
pip3 install --upgrade -r requirements.txt
```

**Still having issues?**
Run from source with `npm start` instead of using the DMG.

