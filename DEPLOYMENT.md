# Gnome Deployment Guide

## Building the .dmg Installer

### Prerequisites
```bash
cd /Users/kennethfrisardiii/Downloads/gnome/electron
npm install
```

### Build Command
```bash
npm run build
```

This will:
1. Bundle the Electron app
2. Include Python backend + dependencies
3. Create a .dmg installer
4. Output to `electron/dist/`

Build time: ~5-10 minutes

### Output Files
```
electron/dist/
├── Gnome-1.0.0.dmg          # macOS installer (distribute this)
├── Gnome-1.0.0-arm64.dmg    # Apple Silicon
├── Gnome-1.0.0-x64.dmg      # Intel Mac
└── mac/                      # Unpacked app (for testing)
```

## Uploading to gnom3.com

### Option 1: GitHub Releases (Recommended for MVP)
1. Go to https://github.com/veselyo/gnome/releases
2. Click "Create a new release"
3. Tag: `v1.0.0`
4. Title: "Gnome v1.0.0 - Initial Release"
5. Upload `Gnome-1.0.0.dmg`
6. Publish release
7. Get download URL: `https://github.com/veselyo/gnome/releases/download/v1.0.0/Gnome-1.0.0.dmg`

### Option 2: Direct Server Upload
If you have FTP/SSH access to gnom3.com:

```bash
# Example with SCP
scp electron/dist/Gnome-1.0.0.dmg user@gnom3.com:/var/www/html/downloads/

# Example with rsync
rsync -avz electron/dist/Gnome-1.0.0.dmg user@gnom3.com:/var/www/html/downloads/
```

### Option 3: Vercel Blob Storage
```bash
npm install -g vercel

# Upload
vercel blob put electron/dist/Gnome-1.0.0.dmg
```

### Option 4: AWS S3
```bash
aws s3 cp electron/dist/Gnome-1.0.0.dmg s3://gnom3-downloads/Gnome-1.0.0.dmg --acl public-read
```

## Deploying Landing Page

### Files to Upload
1. `landing-page.html` → `index.html` on gnom3.com
2. `Gnome-1.0.0.dmg` → same directory

### Directory Structure
```
gnom3.com/
├── index.html                # Landing page
├── Gnome-1.0.0.dmg          # Installer
└── installation-guide.html   # Optional: formatted version of INSTALLATION.md
```

### Quick Deploy with Vercel
```bash
cd /Users/kennethfrisardiii/Downloads/gnome
vercel --prod
```

### Quick Deploy with Netlify
```bash
cd /Users/kennethfrisardiii/Downloads/gnome
netlify deploy --prod --dir=.
```

## DNS Configuration

Point gnom3.com to your hosting:

### For Vercel:
```
Type: CNAME
Name: @
Value: cname.vercel-dns.com
```

### For Netlify:
```
Type: A
Name: @
Value: 75.2.60.5
```

### For Static Host:
```
Type: A
Name: @
Value: [your server IP]
```

## Post-Deployment Checklist

- [ ] Landing page loads at https://gnom3.com
- [ ] Download button points to correct .dmg URL
- [ ] .dmg file downloads successfully
- [ ] .dmg is ~150-250MB in size
- [ ] App installs correctly on fresh Mac
- [ ] App launches and shows UI
- [ ] Can upload PDF successfully
- [ ] Search functionality works
- [ ] Installation instructions are clear

## Monitoring & Analytics (Optional)

Add to `landing-page.html` before `</head>`:

### Google Analytics
```html
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-XXXXXXXXXX');
</script>
```

### Plausible Analytics
```html
<script defer data-domain="gnom3.com" src="https://plausible.io/js/script.js"></script>
```

## Version Updates

When releasing v1.0.1:

1. Update `electron/package.json` version
2. Rebuild: `npm run build`
3. Upload new .dmg
4. Update download link in landing page
5. Add changelog to GitHub releases

## Cost Breakdown

- **Domain (gnom3.com)**: $0 (you own it)
- **Hosting**: 
  - GitHub Releases: Free
  - Vercel: Free tier
  - Netlify: Free tier
- **Total**: $0/month for MVP! 🎉

## Security Notes

- .dmg is NOT code-signed (Apple Developer: $99/year)
- Users will see "unidentified developer" warning
- This is OK for MVP/beta
- For production: sign with Apple Developer cert

## Support

After deployment, monitor:
- GitHub Issues for bug reports
- Download counts (GitHub Insights)
- User feedback

Good luck with the launch! 🚀


