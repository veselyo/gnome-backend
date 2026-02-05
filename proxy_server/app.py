"""
Gnome Proxy Server

This server holds your API keys and OAuth secrets securely.
The Gnome desktop app calls this server instead of the APIs directly.

Deploy to Railway:
1. railway login
2. railway init
3. railway up
4. Add environment variables in Railway dashboard

Environment variables needed:
- VOYAGE_API_KEY
- PINECONE_API_KEY
- PINECONE_HOST
- GOOGLE_CLIENT_SECRET
- MICROSOFT_CLIENT_SECRET
"""

from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
import voyageai
from pinecone import Pinecone
import os
import logging
import requests
from urllib.parse import urlencode, quote

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Allow requests from Electron app

# Initialize clients (keys from environment)
voyage_client = None
pinecone_index = None

def get_voyage_client():
    global voyage_client
    if voyage_client is None:
        api_key = os.environ.get('VOYAGE_API_KEY')
        if not api_key:
            raise ValueError("VOYAGE_API_KEY not set")
        voyage_client = voyageai.Client(api_key=api_key)
    return voyage_client

def get_pinecone_index():
    global pinecone_index
    if pinecone_index is None:
        api_key = os.environ.get('PINECONE_API_KEY')
        host = os.environ.get('PINECONE_HOST')
        if not api_key or not host:
            raise ValueError("PINECONE_API_KEY or PINECONE_HOST not set")
        pc = Pinecone(api_key=api_key)
        pinecone_index = pc.Index(host=host)
    return pinecone_index


# ============ OAuth Configuration ============

# These secrets are stored on the server only - never exposed to the app
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
MICROSOFT_CLIENT_SECRET = os.environ.get('MICROSOFT_CLIENT_SECRET')

# Client IDs are public (also baked into app)
GOOGLE_CLIENT_ID = '200229085583-tasbpc46mnl4ahs2hj3ouqtmjf1jdnv5.apps.googleusercontent.com'
MICROSOFT_CLIENT_ID = '9ff39189-1c55-4b23-8cb2-fdeebffe1d70'


# ============ OAuth Endpoints ============

@app.route('/oauth/google/callback')
def google_oauth_callback():
    """
    Handle Google OAuth callback.
    Exchange the authorization code for tokens using the CLIENT_SECRET on server.
    Return tokens to the app via redirect to custom URL scheme.
    """
    try:
        code = request.args.get('code')
        state = request.args.get('state', '')  # Contains: service|redirect_port
        error = request.args.get('error')

        if error:
            logger.error(f"Google OAuth error: {error}")
            return redirect(f'http://localhost:5001/api/oauth/callback?error={quote(error)}&state={quote(state)}')

        if not code:
            return redirect(f'http://localhost:5001/api/oauth/callback?error=no_code&state={quote(state)}')

        if not GOOGLE_CLIENT_SECRET:
            logger.error("GOOGLE_CLIENT_SECRET not configured on server")
            return redirect(f'http://localhost:5001/api/oauth/callback?error=server_not_configured&state={quote(state)}')

        # Determine the redirect URI (must match what was used in the auth request)
        # Force HTTPS since Railway proxies HTTPS -> HTTP internally
        redirect_uri = request.url_root.rstrip('/') + '/oauth/google/callback'
        redirect_uri = redirect_uri.replace('http://', 'https://')

        # Exchange code for tokens
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }

        logger.info(f"Google token exchange - redirect_uri: {redirect_uri}")
        response = requests.post(token_url, data=token_data)

        if response.status_code != 200:
            logger.error(f"Google token exchange failed (status {response.status_code}): {response.text}")
            # Include more detail in error
            error_detail = response.json().get('error_description', 'token_exchange_failed') if response.text else 'token_exchange_failed'
            return redirect(f'http://localhost:5001/api/oauth/callback?error={quote(error_detail)}&state={quote(state)}')

        tokens = response.json()

        # Get user email for account identification
        access_token = tokens.get('access_token')
        userinfo_response = requests.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'}
        )

        email = ''
        if userinfo_response.status_code == 200:
            userinfo = userinfo_response.json()
            email = userinfo.get('email', '')

        # Redirect back to the local app with tokens
        callback_params = {
            'access_token': tokens.get('access_token', ''),
            'refresh_token': tokens.get('refresh_token', ''),
            'expires_in': tokens.get('expires_in', 3600),
            'token_type': tokens.get('token_type', 'Bearer'),
            'email': email,
            'state': state
        }

        callback_url = f'http://localhost:5001/api/oauth/callback?{urlencode(callback_params)}'
        return redirect(callback_url)

    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        return redirect(f'http://localhost:5001/api/oauth/callback?error={quote(str(e))}&state={quote(state)}')


@app.route('/oauth/microsoft/callback')
def microsoft_oauth_callback():
    """
    Handle Microsoft OAuth callback.
    Exchange the authorization code for tokens using the CLIENT_SECRET on server.
    Return tokens to the app via redirect.
    """
    try:
        code = request.args.get('code')
        state = request.args.get('state', '')  # Contains: service (outlook or onedrive)
        error = request.args.get('error')
        error_description = request.args.get('error_description', '')

        if error:
            logger.error(f"Microsoft OAuth error: {error} - {error_description}")
            return redirect(f'http://localhost:5001/api/oauth/callback?error={quote(error)}&state={quote(state)}')

        if not code:
            return redirect(f'http://localhost:5001/api/oauth/callback?error=no_code&state={quote(state)}')

        if not MICROSOFT_CLIENT_SECRET:
            logger.error("MICROSOFT_CLIENT_SECRET not configured on server")
            return redirect(f'http://localhost:5001/api/oauth/callback?error=server_not_configured&state={quote(state)}')

        # Determine the redirect URI (must match what was used in the auth request)
        # Force HTTPS since Railway proxies HTTPS -> HTTP internally
        redirect_uri = request.url_root.rstrip('/') + '/oauth/microsoft/callback'
        redirect_uri = redirect_uri.replace('http://', 'https://')

        # Exchange code for tokens
        token_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
        token_data = {
            'code': code,
            'client_id': MICROSOFT_CLIENT_ID,
            'client_secret': MICROSOFT_CLIENT_SECRET,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }

        response = requests.post(token_url, data=token_data)

        if response.status_code != 200:
            logger.error(f"Microsoft token exchange failed: {response.text}")
            return redirect(f'http://localhost:5001/api/oauth/callback?error=token_exchange_failed&state={quote(state)}')

        tokens = response.json()

        # Get user email for account identification
        access_token = tokens.get('access_token')
        graph_response = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers={'Authorization': f'Bearer {access_token}'}
        )

        email = ''
        if graph_response.status_code == 200:
            user_data = graph_response.json()
            email = user_data.get('mail') or user_data.get('userPrincipalName', '')

        # Redirect back to the local app with tokens
        callback_params = {
            'access_token': tokens.get('access_token', ''),
            'refresh_token': tokens.get('refresh_token', ''),
            'expires_in': tokens.get('expires_in', 3600),
            'token_type': tokens.get('token_type', 'Bearer'),
            'email': email,
            'state': state
        }

        callback_url = f'http://localhost:5001/api/oauth/callback?{urlencode(callback_params)}'
        return redirect(callback_url)

    except Exception as e:
        logger.error(f"Microsoft OAuth callback error: {e}")
        return redirect(f'http://localhost:5001/api/oauth/callback?error={quote(str(e))}&state={quote(state)}')


# ============ Token Refresh Endpoints ============

@app.route('/oauth/google/refresh', methods=['POST'])
def google_token_refresh():
    """Refresh Google OAuth tokens."""
    try:
        data = request.json
        refresh_token = data.get('refresh_token')

        if not refresh_token:
            return jsonify({'error': 'No refresh token provided'}), 400

        if not GOOGLE_CLIENT_SECRET:
            return jsonify({'error': 'Server not configured for Google OAuth'}), 500

        # Exchange refresh token for new access token
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }

        response = requests.post(token_url, data=token_data)

        if response.status_code != 200:
            logger.error(f"Google token refresh failed: {response.text}")
            return jsonify({'error': 'Token refresh failed'}), 400

        tokens = response.json()
        return jsonify({
            'access_token': tokens.get('access_token'),
            'expires_in': tokens.get('expires_in', 3600),
            'token_type': tokens.get('token_type', 'Bearer')
        })

    except Exception as e:
        logger.error(f"Google token refresh error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/oauth/microsoft/refresh', methods=['POST'])
def microsoft_token_refresh():
    """Refresh Microsoft OAuth tokens."""
    try:
        data = request.json
        refresh_token = data.get('refresh_token')

        if not refresh_token:
            return jsonify({'error': 'No refresh token provided'}), 400

        if not MICROSOFT_CLIENT_SECRET:
            return jsonify({'error': 'Server not configured for Microsoft OAuth'}), 500

        # Exchange refresh token for new access token
        token_url = 'https://login.microsoftonline.com/common/oauth2/v2.0/token'
        token_data = {
            'client_id': MICROSOFT_CLIENT_ID,
            'client_secret': MICROSOFT_CLIENT_SECRET,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }

        response = requests.post(token_url, data=token_data)

        if response.status_code != 200:
            logger.error(f"Microsoft token refresh failed: {response.text}")
            return jsonify({'error': 'Token refresh failed'}), 400

        tokens = response.json()
        return jsonify({
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),  # Microsoft may return a new refresh token
            'expires_in': tokens.get('expires_in', 3600),
            'token_type': tokens.get('token_type', 'Bearer')
        })

    except Exception as e:
        logger.error(f"Microsoft token refresh error: {e}")
        return jsonify({'error': str(e)}), 500


# ============ Embedding Endpoints ============

@app.route('/api/embed', methods=['POST'])
def embed():
    """Generate embeddings for texts using Voyage AI."""
    try:
        data = request.json
        texts = data.get('texts', [])
        input_type = data.get('input_type', 'document')

        if not texts:
            return jsonify({'error': 'No texts provided'}), 400

        # Voyage AI has batch limits, process in chunks
        MAX_BATCH = 128
        all_embeddings = []

        client = get_voyage_client()

        for i in range(0, len(texts), MAX_BATCH):
            batch = texts[i:i + MAX_BATCH]
            result = client.embed(batch, model='voyage-3', input_type=input_type)
            all_embeddings.extend(result.embeddings)

        return jsonify({'embeddings': all_embeddings})

    except Exception as e:
        logger.error(f"Embed error: {e}")
        return jsonify({'error': str(e)}), 500


# ============ Vector Database Endpoints ============

@app.route('/api/search', methods=['POST'])
def search():
    """Search vectors in Pinecone."""
    try:
        data = request.json
        embedding = data.get('embedding')
        namespace = data.get('namespace')
        top_k = data.get('top_k', 20)
        filter_dict = data.get('filter')

        if not embedding:
            return jsonify({'error': 'No embedding provided'}), 400
        if not namespace:
            return jsonify({'error': 'No namespace provided'}), 400

        index = get_pinecone_index()

        results = index.query(
            vector=embedding,
            namespace=namespace,
            top_k=top_k,
            filter=filter_dict,
            include_metadata=True
        )

        # Convert to dict for JSON serialization
        matches = []
        for match in results.matches:
            matches.append({
                'id': match.id,
                'score': match.score,
                'metadata': match.metadata
            })

        return jsonify({'matches': matches})

    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/index', methods=['POST'])
def index_vectors():
    """Upsert vectors into Pinecone."""
    try:
        data = request.json
        vectors = data.get('vectors', [])
        namespace = data.get('namespace')

        if not vectors:
            return jsonify({'error': 'No vectors provided'}), 400
        if not namespace:
            return jsonify({'error': 'No namespace provided'}), 400

        index = get_pinecone_index()

        # Pinecone batch limit is 100
        BATCH_SIZE = 100
        for i in range(0, len(vectors), BATCH_SIZE):
            batch = vectors[i:i + BATCH_SIZE]
            index.upsert(vectors=batch, namespace=namespace)

        return jsonify({'success': True, 'count': len(vectors)})

    except Exception as e:
        logger.error(f"Index error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete', methods=['POST'])
def delete_vectors():
    """Delete vectors from Pinecone."""
    try:
        data = request.json
        ids = data.get('ids')
        namespace = data.get('namespace')
        filter_dict = data.get('filter')
        delete_all = data.get('delete_all', False)

        if not namespace:
            return jsonify({'error': 'No namespace provided'}), 400

        index = get_pinecone_index()

        if delete_all:
            index.delete(delete_all=True, namespace=namespace)
        elif ids:
            index.delete(ids=ids, namespace=namespace)
        elif filter_dict:
            index.delete(filter=filter_dict, namespace=namespace)
        else:
            return jsonify({'error': 'No ids, filter, or delete_all specified'}), 400

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats', methods=['POST'])
def get_stats():
    """Get index statistics for a namespace."""
    try:
        data = request.json or {}
        namespace = data.get('namespace')

        index = get_pinecone_index()
        stats = index.describe_index_stats()

        result = {
            'total_vector_count': stats.total_vector_count,
            'dimension': stats.dimension
        }

        if namespace and namespace in stats.namespaces:
            result['namespace_vector_count'] = stats.namespaces[namespace].vector_count

        return jsonify(result)

    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({'error': str(e)}), 500


# ============ Health Check ============

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'voyage_configured': os.environ.get('VOYAGE_API_KEY') is not None,
        'pinecone_configured': os.environ.get('PINECONE_API_KEY') is not None,
        'google_oauth_configured': GOOGLE_CLIENT_SECRET is not None,
        'microsoft_oauth_configured': MICROSOFT_CLIENT_SECRET is not None
    })


@app.route('/', methods=['GET'])
def root():
    """Root endpoint."""
    return jsonify({
        'service': 'Gnome Proxy Server',
        'version': '1.1.0',
        'endpoints': [
            'POST /api/embed - Generate embeddings',
            'POST /api/search - Search vectors',
            'POST /api/index - Index vectors',
            'POST /api/delete - Delete vectors',
            'POST /api/stats - Get index stats',
            'GET /oauth/google/callback - Google OAuth callback',
            'GET /oauth/microsoft/callback - Microsoft OAuth callback',
            'POST /oauth/google/refresh - Refresh Google tokens',
            'POST /oauth/microsoft/refresh - Refresh Microsoft tokens',
            'GET /health - Health check'
        ]
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting Gnome Proxy Server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
