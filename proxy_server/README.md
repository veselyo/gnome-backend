# Gnome Proxy Server

This server handles all secrets for the Gnome app:
- **API Keys**: Voyage AI (embeddings) and Pinecone (vector database)
- **OAuth Secrets**: Google and Microsoft CLIENT_SECRETs for OAuth token exchange

Users download the app and it just works - no configuration needed.

## Architecture

```
User clicks "Connect Google Drive"
        │
        ▼
App opens browser → Google login page
        │
        ▼
User authorizes → Google redirects to PROXY with auth code
        │
        ▼
Proxy exchanges code for tokens (using CLIENT_SECRET on server)
        │
        ▼
Proxy redirects to app at localhost:5001 with tokens
        │
        ▼
App stores tokens locally, uses them for Google API calls
```

## What's Baked Into the App (Safe)

| Item | Purpose | Safe? |
|------|---------|-------|
| `GOOGLE_CLIENT_ID` | Identifies app to Google | ✅ Yes - public |
| `MICROSOFT_CLIENT_ID` | Identifies app to Microsoft | ✅ Yes - public |
| `PROXY_URL` | Your Railway server address | ✅ Yes - just a URL |

## What's on the Proxy Server (Secrets)

| Item | Purpose |
|------|---------|
| `VOYAGE_API_KEY` | Embeddings API |
| `PINECONE_API_KEY` | Vector database |
| `PINECONE_HOST` | Pinecone endpoint |
| `GOOGLE_CLIENT_SECRET` | OAuth token exchange |
| `MICROSOFT_CLIENT_SECRET` | OAuth token exchange |

## Deploy to Railway

### 1. Install Railway CLI
```bash
npm install -g @railway/cli
railway login
```

### 2. Deploy
```bash
cd proxy_server
railway init
railway up
```

### 3. Add Environment Variables

In the Railway dashboard (https://railway.app), add:

| Variable | Description | Where to Get |
|----------|-------------|--------------|
| `VOYAGE_API_KEY` | Voyage AI API key | https://www.voyageai.com |
| `PINECONE_API_KEY` | Pinecone API key | https://www.pinecone.io |
| `PINECONE_HOST` | Pinecone index host URL | Pinecone dashboard |
| `GOOGLE_CLIENT_SECRET` | Google OAuth secret | Google Cloud Console |
| `MICROSOFT_CLIENT_SECRET` | Microsoft OAuth secret | Azure Portal |

### 4. Update OAuth Redirect URIs

After deploying, update your OAuth providers with the proxy callback URLs:

**Google Cloud Console** (https://console.cloud.google.com):
1. Go to APIs & Services → Credentials
2. Edit your OAuth client
3. Add redirect URI: `https://gnome-production.up.railway.app/oauth/google/callback`

**Azure Portal** (https://portal.azure.com):
1. Go to App registrations → Your app
2. Add redirect URI: `https://gnome-production.up.railway.app/oauth/microsoft/callback`

### 5. Test the Deployment

```bash
# Health check
curl https://gnome-production.up.railway.app/health

# Test embedding
curl -X POST https://gnome-production.up.railway.app/api/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["test query"], "input_type": "query"}'
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/embed` | POST | Generate embeddings |
| `/api/search` | POST | Search vectors |
| `/api/index` | POST | Index vectors |
| `/api/delete` | POST | Delete vectors |
| `/api/stats` | POST | Get index stats |
| `/oauth/google/callback` | GET | Google OAuth callback |
| `/oauth/microsoft/callback` | GET | Microsoft OAuth callback |
| `/oauth/google/refresh` | POST | Refresh Google tokens |
| `/oauth/microsoft/refresh` | POST | Refresh Microsoft tokens |

## Security Notes

- The proxy server has no authentication for embedding/search endpoints
- Each user gets an isolated namespace based on their machine ID
- OAuth secrets are stored only on the proxy server
- Token exchange happens server-side, secrets never touch the app

## Cost Estimates

- **Railway**: ~$5/month for basic usage
- **Voyage AI**: ~$0.10 per 1M tokens
- **Pinecone**: Free tier up to 100K vectors, then ~$70/month

## Troubleshooting

**OAuth "redirect_uri_mismatch" error:**
- Ensure the redirect URI in Google/Azure matches exactly: `https://gnome-production.up.railway.app/oauth/google/callback`

**"Connection refused" error:**
- Server may be sleeping (free tier). Make a request to wake it up.
- Check Railway dashboard for deployment status

**Slow responses:**
- First request after sleep takes ~5-10 seconds
- Consider upgrading Railway plan to prevent sleeping
