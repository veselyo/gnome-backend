# Gnome Installation Guide

## macOS Installation

### Step 1: Download
1. Go to gnom3.com
2. Click "Download for macOS"
3. Save `Gnome-1.0.0.dmg` to your Downloads folder

### Step 2: Install
1. Double-click `Gnome-1.0.0.dmg` to open the installer
2. Drag the Gnome icon to the Applications folder
3. Close the installer window
4. Eject the Gnome disk image (if mounted)

### Step 3: First Launch (Important!)
Since Gnome is not notarized, macOS will block it on first launch:

**Method 1: Right-Click Method (Recommended)**
1. Go to Applications folder
2. Find Gnome.app
3. **Right-click** (or Control+click) on Gnome.app
4. Select "Open" from the menu
5. Click "Open" in the security dialog
6. The app will launch

**Method 2: Security Settings**
1. Try to open Gnome normally (it will be blocked)
2. Go to System Preferences → Security & Privacy → General
3. You'll see a message about Gnome being blocked
4. Click "Open Anyway"
5. Confirm by clicking "Open"

### Step 4: API Key Setup
On first launch, you'll need to provide:

1. **Voyage AI API Key**
   - Sign up at https://www.voyageai.com/
   - Get your API key from the dashboard
   - Paste it into Gnome

2. **Pinecone API Key & Host**
   - Sign up at https://www.pinecone.io/
   - Create a new index (1024 dimensions, cosine similarity)
   - Get your API key and host URL
   - Paste both into Gnome

### Step 5: Start Using Gnome
1. Upload your first PDF (drag & drop or click Upload)
2. Wait for processing (takes ~5-10 seconds per PDF)
3. Search using natural language
4. Example: "tax documents", "resume", "physics homework"

## Troubleshooting

### "Gnome is damaged and can't be opened"
This happens when the app signature is invalid. Solution:
```bash
xattr -cr /Applications/Gnome.app
```
Then try opening again using the Right-Click method.

### "Port 5001 already in use"
Another app is using port 5001. Solution:
```bash
lsof -ti:5001 | xargs kill -9
```
Then relaunch Gnome.

### Flask Backend Won't Start
Make sure you have Python 3.9+ installed:
```bash
python3 --version
```

### API Keys Not Working
- Double-check keys are copied correctly (no extra spaces)
- Verify your Pinecone index is created with 1024 dimensions
- Check you have credits/quota remaining on both services

### App Crashes on Launch
1. Check Console.app for error logs
2. Ensure macOS 11.0+ 
3. Try reinstalling the app

## Uninstalling Gnome

1. Quit Gnome if it's running
2. Delete `/Applications/Gnome.app`
3. Delete app data (optional):
   ```bash
   rm -rf ~/Library/Application\ Support/gnome
   ```

## System Requirements

- **OS**: macOS 11.0 (Big Sur) or later
- **RAM**: 4GB minimum, 8GB recommended
- **Storage**: 200MB for app, plus space for your PDFs
- **CPU**: Apple Silicon (M1/M2/M3) or Intel x64
- **Internet**: Required for first setup and document processing

## Getting Help

- GitHub Issues: https://github.com/veselyo/gnome/issues
- Email: support@gnom3.com (if you have the domain set up)

## Privacy & Data

- Your PDFs are stored locally on your machine
- Embeddings are stored in your Pinecone account
- No data is sent to Gnome servers (we don't have any!)
- You control your API keys and data


