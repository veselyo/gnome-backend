# Quick OAuth Setup (5 Minutes Each)

## 🔑 Google Drive - Fast Setup

### 1. Create Project (2 minutes)
```
1. Go to: https://console.cloud.google.com/projectcreate
2. Project name: "Gnome"
3. Click "Create"
```

### 2. Enable Drive API (1 minute)
```
1. Search for "Google Drive API" in the search bar
2. Click "Google Drive API"
3. Click "Enable"
```

### 3. Create OAuth Credentials (2 minutes)
```
1. Left sidebar → "APIs & Services" → "Credentials"
2. Click "Configure Consent Screen"
   - User Type: External
   - App name: Gnome
   - User support email: [your email]
   - Developer email: [your email]
   - Click "Save and Continue" (skip scopes)
   - Add test user: [your Google email]
   - Click "Save and Continue"
   - Click "Back to Dashboard"

3. Click "Create Credentials" → "OAuth client ID"
   - Application type: Desktop app
   - Name: Gnome Desktop
   - Click "Create"
   
4. COPY the Client ID and Client Secret
```

### 4. Add to .env
```bash
# Add these lines to /Users/kennethfrisardiii/Downloads/gnome/.env
GOOGLE_CLIENT_ID="PASTE_CLIENT_ID_HERE.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="PASTE_CLIENT_SECRET_HERE"

# Also add to electron/.env
# Also add to ~/.gnome-env (for packaged app)
```

---

## 🔑 OneDrive - Fast Setup

### 1. Register App (2 minutes)
```
1. Go to: https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
2. Click "New registration"
3. Name: Gnome
4. Supported account types: "Personal Microsoft accounts only"
5. Redirect URI: Skip for now
6. Click "Register"
```

### 2. Get Client ID (1 second)
```
1. On the Overview page, copy "Application (client) ID"
```

### 3. Create Client Secret (1 minute)
```
1. Left sidebar → "Certificates & secrets"
2. Click "New client secret"
3. Description: "Gnome desktop"
4. Expires: 24 months
5. Click "Add"
6. COPY the "Value" (shown only once!)
```

### 4. Set API Permissions (1 minute)
```
1. Left sidebar → "API permissions"
2. Click "Add a permission"
3. Choose "Microsoft Graph"
4. Choose "Delegated permissions"
5. Search and check:
   - Files.Read.All
   - offline_access
6. Click "Add permissions"
7. (Optional) Click "Grant admin consent"
```

### 5. Add to .env
```bash
# Add these lines
MICROSOFT_CLIENT_ID="PASTE_APPLICATION_ID_HERE"
MICROSOFT_CLIENT_SECRET="PASTE_CLIENT_SECRET_HERE"
```

---

## ✅ Test Connections

After adding credentials, restart Gnome:
```bash
cd /Users/kennethfrisardiii/Downloads/gnome/electron
npm start
```

Then:
1. Click "Settings"
2. Click "Connect" on Google Drive
   - Browser opens
   - Login with Google
   - Allow permissions
   - Returns to app
   - Starts syncing!

3. Click "Connect" on OneDrive  
   - Shows device code
   - Visit link in browser
   - Enter code
   - Allow permissions
   - Returns to app
   - Starts syncing!

## 🐛 Common Issues

**"OAuth not configured":**
- Make sure env vars are set
- Restart the app after adding them
- Check for typos in .env

**Browser doesn't open (Google):**
- Port 8080 might be in use
- Check terminal for OAuth URL
- Open manually

**Device code doesn't work (OneDrive):**
- Code expires in 15 minutes
- Visit: https://microsoft.com/devicelogin
- Enter the code shown in terminal

## 🎯 Current Status

You need to:
1. [ ] Create Google Cloud project
2. [ ] Add Google credentials to .env
3. [ ] Create Azure app registration
4. [ ] Add Microsoft credentials to .env
5. [ ] Restart Gnome
6. [ ] Test connections

**Time needed: 10-15 minutes total**

