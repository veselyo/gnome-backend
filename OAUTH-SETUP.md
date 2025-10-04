# OAuth Setup for Google Drive & OneDrive

## 🔑 Google Drive Setup (5 minutes)

### Step 1: Create Google Cloud Project

1. Go to https://console.cloud.google.com/
2. Create new project → Name it "Gnome"
3. Select the project

### Step 2: Enable Drive API

1. Go to "APIs & Services" → "Library"
2. Search for "Google Drive API"
3. Click "Enable"

### Step 3: Create OAuth Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. Configure consent screen (if asked):
   - User Type: External
   - App name: Gnome
   - User support email: your email
   - Developer email: your email
   - Scopes: Leave empty
   - Test users: Add your Google email
   - Save
4. Create OAuth client ID:
   - Application type: "Desktop app"
   - Name: "Gnome Desktop"
   - Click "Create"
5. **Download JSON** or copy Client ID and Client Secret

### Step 4: Add to .env

Add these to `/Users/kennethfrisardiii/Downloads/gnome/.env`:

```bash
GOOGLE_CLIENT_ID="your_client_id_here.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your_client_secret_here"
```

Also add to `electron/.env` for the packaged app!

---

## 🔑 OneDrive Setup (5 minutes)

### Step 1: Register App in Azure

1. Go to https://portal.azure.com/
2. Search for "Azure Active Directory" or "Microsoft Entra ID"
3. Click "App registrations" → "New registration"

### Step 2: Configure App

1. Name: "Gnome"
2. Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
3. Redirect URI: 
   - Platform: "Mobile and desktop applications"
   - URI: `http://localhost`
4. Click "Register"

### Step 3: Get Credentials

1. Copy the **Application (client) ID**
2. Go to "Certificates & secrets"
3. Click "New client secret"
4. Description: "Gnome desktop"
5. Expires: 24 months
6. Click "Add"
7. **Copy the secret VALUE** (only shown once!)

### Step 4: Set Permissions

1. Go to "API permissions"
2. Click "Add a permission"
3. Choose "Microsoft Graph"
4. Choose "Delegated permissions"
5. Add these permissions:
   - `Files.Read.All`
   - `offline_access`
6. Click "Add permissions"
7. (Optional) Click "Grant admin consent" if you're admin

### Step 5: Add to .env

Add these to `/Users/kennethfrisardiii/Downloads/gnome/.env`:

```bash
MICROSOFT_CLIENT_ID="your_application_id_here"
MICROSOFT_CLIENT_SECRET="your_client_secret_here"
```

Also add to `electron/.env`!

---

## 🧪 Testing OAuth

### Test Google Drive:

```bash
cd /Users/kennethfrisardiii/Downloads/gnome
source venv/bin/activate
source .env
python3 -c "
from database.models import GnomeDatabase
from sync_engine.gdrive_sync import GoogleDriveSyncEngine
db = GnomeDatabase()
engine = GoogleDriveSyncEngine(db)
print('Testing Google Drive auth...')
success = engine.authenticate()
print(f'Success: {success}')
"
```

### Test OneDrive:

```bash
python3 -c "
from database.models import GnomeDatabase  
from sync_engine.onedrive_sync import OneDriveSyncEngine
db = GnomeDatabase()
engine = OneDriveSyncEngine(db)
print('Testing OneDrive auth...')
success = engine.authenticate()
print(f'Success: {success}')
"
```

---

## 🚨 Troubleshooting

**"Client ID not found":**
- Make sure env vars are set correctly
- Restart the app after adding env vars

**"Invalid grant" (Google):**
- Make sure you added your email as a test user
- App must be in "Testing" mode

**"Invalid client" (OneDrive):**
- Check client ID and secret are correct
- Make sure redirect URI is exactly `http://localhost`

**OAuth opens but fails:**
- Check you're logged into the right account
- Try in incognito/private browser window

---

## ⚡ Quick Start (Skip OAuth for MVP):

**For Sunday demo, you can skip OAuth and just demo:**
- ✅ Finder with 1,147 files (already working!)
- ✅ Semantic search
- ✅ Click to open files
- ✅ Beautiful UI

**Add Google Drive/OneDrive OAuth later** when you have 10 minutes to set up the apps.

---

## 📝 Current .env Template:

```bash
# Existing
VOYAGE_API_KEY=your_key_here
PINECONE_API_KEY=your_key_here
PINECONE_HOST=your_host_here

# Add these for Google Drive (optional for MVP)
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret

# Add these for OneDrive (optional for MVP)
MICROSOFT_CLIENT_ID=your_app_id_here
MICROSOFT_CLIENT_SECRET=your_client_secret_here
```

Save this in both:
- `/Users/kennethfrisardiii/Downloads/gnome/.env`
- `/Users/kennethfrisardiii/Downloads/gnome/electron/.env`
- `~/.gnome-env` (for packaged app)

