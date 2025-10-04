# 🚀 Gnome v1.0.0 Release Checklist

## ✅ Completed

- [x] Electron wrapper created
- [x] Flask backend integrated
- [x] Desktop app working
- [x] DMG installers built
  - Gnome-1.0.0.dmg (94MB) - Intel
  - Gnome-1.0.0-arm64.dmg (89MB) - Apple Silicon
- [x] Documentation created
  - README.md
  - INSTALLATION.md
  - DEPLOYMENT.md
  - landing-page.html
- [x] Code pushed to GitHub (mvp branch)

## 📦 DMG Files Location

```
/Users/kennethfrisardiii/Downloads/gnome/electron/dist/
├── Gnome-1.0.0.dmg          (Intel Mac)
└── Gnome-1.0.0-arm64.dmg    (Apple Silicon)
```

## 🌐 Upload to GitHub Releases (Recommended)

### Step 1: Create Release on GitHub

1. Go to: https://github.com/veselyo/gnome/releases
2. Click "Create a new release"
3. Fill in:
   - **Tag**: `v1.0.0`
   - **Release title**: `Gnome v1.0.0 - Initial Release`
   - **Description**:
   ```markdown
   ## Gnome v1.0.0 - AI-Powered Semantic PDF Search
   
   First public release of Gnome desktop app!
   
   ### ✨ Features
   - Semantic PDF search using AI
   - Powered by Voyage AI + Pinecone
   - Beautiful macOS-native interface
   - Drag & drop PDF upload
   - Natural language queries
   
   ### 📥 Download
   - **Apple Silicon (M1/M2/M3)**: Gnome-1.0.0-arm64.dmg
   - **Intel Mac**: Gnome-1.0.0.dmg
   
   ### ⚠️ First Launch
   Right-click the app → Open (required for unsigned apps)
   
   ### 📚 Documentation
   - [Installation Guide](https://github.com/veselyo/gnome/blob/mvp/INSTALLATION.md)
   - [README](https://github.com/veselyo/gnome/blob/mvp/README.md)
   
   ### 🔑 Requirements
   - macOS 11.0+
   - Voyage AI API key
   - Pinecone API key
   ```

4. Drag and drop both .dmg files into the upload area
5. Click "Publish release"

### Step 2: Get Download URLs

After publishing, the URLs will be:
```
Intel Mac:
https://github.com/veselyo/gnome/releases/download/v1.0.0/Gnome-1.0.0.dmg

Apple Silicon:
https://github.com/veselyo/gnome/releases/download/v1.0.0/Gnome-1.0.0-arm64.dmg
```

## 🌍 Deploy Landing Page to gnom3.com

### Option A: Manual Upload (If you have FTP/SSH)

```bash
# Upload landing page
scp landing-page.html user@gnom3.com:/var/www/html/index.html

# Or use FileZilla/Cyberduck to upload:
# - landing-page.html → rename to index.html on server
```

### Option B: Use GitHub Pages (Free)

1. Create `docs` folder:
```bash
mkdir -p docs
cp landing-page.html docs/index.html
```

2. Update download links in docs/index.html to GitHub Release URLs

3. Push to GitHub:
```bash
git add docs/
git commit -m "Add landing page for GitHub Pages"
git push origin mvp
```

4. Go to Settings → Pages → Set source to `docs` folder

### Option C: Deploy to Vercel (Recommended - Free & Fast)

```bash
cd /Users/kennethfrisardiii/Downloads/gnome
vercel --prod
```

Then set gnom3.com to point to Vercel in your DNS.

## 📝 Update Landing Page Download Links

In `landing-page.html`, change:

```html
<a href="Gnome-1.0.0.dmg" class="download-btn" download>
```

To:

```html
<a href="https://github.com/veselyo/gnome/releases/download/v1.0.0/Gnome-1.0.0-arm64.dmg" class="download-btn">
```

## 🧪 Test Installation (IMPORTANT!)

Before going public:

1. Test on a **clean Mac** (or create new user account)
2. Download the .dmg
3. Open and drag to Applications
4. Right-click → Open
5. Enter API keys
6. Upload a PDF
7. Test search

## 📊 Post-Launch Monitoring

Track:
- Download counts (GitHub Insights)
- Issues reported
- User feedback

## 🎯 Sunday Launch Timeline

**Tonight (Oct 4):**
- [ ] Upload DMGs to GitHub Releases
- [ ] Update landing page download links
- [ ] Deploy landing page to gnom3.com
- [ ] Test installation on clean Mac

**Tomorrow Morning (Oct 5):**
- [ ] Final testing
- [ ] Share on social media
- [ ] Send to beta testers
- [ ] Monitor for issues

## 🚨 Known Issues to Document

- App is unsigned (requires right-click → Open)
- Port 5001 might conflict with AirPlay
- Requires Voyage AI + Pinecone API keys
- macOS 11.0+ only

## 💰 Costs

- Domain (gnom3.com): $0 (you own it)
- GitHub Releases: Free
- Vercel hosting: Free
- **Total: $0** 🎉

## 🆘 Support Channels

Set up:
- GitHub Issues for bugs
- Email (if you want): support@gnom3.com
- Twitter/X for updates

---

**You're ready to launch! 🚀**

Good luck hitting that Sunday deadline!

