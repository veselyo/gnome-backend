#!/bin/bash
# Build script that securely bundles API keys into the DMG

set -e

echo "=== Building Gnome DMG with Bundled API Keys ==="
echo ""

# Load API keys from .env
if [ -f "electron/.env" ]; then
    source electron/.env
else
    echo "❌ Error: electron/.env not found"
    exit 1
fi

# Verify keys are loaded
if [ -z "$VOYAGE_API_KEY" ] || [ -z "$PINECONE_API_KEY" ] || [ -z "$COHERE_API_KEY" ]; then
    echo "❌ Error: API keys not found in electron/.env"
    exit 1
fi

echo "✅ API keys loaded from electron/.env"
echo ""

# Base64 encode the keys for obfuscation
VOYAGE_ENCODED=$(echo -n "$VOYAGE_API_KEY" | base64)
PINECONE_ENCODED=$(echo -n "$PINECONE_API_KEY" | base64)
PINECONE_HOST_ENCODED=$(echo -n "$PINECONE_HOST" | base64)
COHERE_ENCODED=$(echo -n "$COHERE_API_KEY" | base64)

# Inject keys into bundled_config.py
echo "🔐 Injecting obfuscated keys into config/bundled_config.py..."
cat > config/bundled_config.py << EOF
"""
Bundled API configuration for Gnome.
This file contains obfuscated API keys for out-of-the-box functionality.
"""
import base64
import os

# Obfuscated API keys (Base64 encoded)
_BUNDLED_KEYS = {
    "VOYAGE_API_KEY": "$VOYAGE_ENCODED",
    "PINECONE_API_KEY": "$PINECONE_ENCODED",
    "PINECONE_HOST": "$PINECONE_HOST_ENCODED",
    "COHERE_API_KEY": "$COHERE_ENCODED"
}

def get_api_key(key_name: str) -> str:
    """
    Get API key with fallback priority:
    1. User's environment variable (if they want to use their own)
    2. User's ~/.gnome-env file
    3. Bundled obfuscated keys (default)
    """
    # Check environment first (user override)
    env_value = os.environ.get(key_name)
    if env_value:
        return env_value
    
    # Check ~/.gnome-env file
    gnome_env = os.path.expanduser('~/.gnome-env')
    if os.path.exists(gnome_env):
        try:
            with open(gnome_env, 'r') as f:
                for line in f:
                    if line.startswith(key_name):
                        return line.split('=', 1)[1].strip()
        except:
            pass
    
    # Fall back to bundled keys
    bundled = _BUNDLED_KEYS.get(key_name, "")
    if bundled:
        try:
            # Decode the base64 obfuscated key
            return base64.b64decode(bundled).decode('utf-8')
        except:
            return ""
    
    return ""
EOF

echo "✅ Keys injected successfully"
echo ""

# Build the DMG
echo "📦 Building DMG with electron-builder..."
cd electron
npm run build

echo ""
echo "✅ Build complete!"
echo ""
echo "DMG files with bundled keys:"
ls -lh dist/*.dmg
echo ""
echo "⚠️  SECURITY: Keys are base64 obfuscated (not encrypted)"
echo "⚠️  Users can extract them if they try hard enough"
echo "✅  But app works out-of-the-box with zero setup!"

