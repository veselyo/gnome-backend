"""
Bundled API configuration for Gnome.
This file contains obfuscated API keys for out-of-the-box functionality.
"""
import base64
import os

# Obfuscated API keys (Base64 encoded)
# Users can override by setting environment variables
_BUNDLED_KEYS = {
    # These will be filled with your actual keys, base64 encoded
    "VOYAGE_API_KEY": "",  # Will be set during build
    "PINECONE_API_KEY": "",
    "PINECONE_HOST": "",
    "COHERE_API_KEY": ""
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

def set_bundled_keys(voyage_key: str, pinecone_key: str, pinecone_host: str, cohere_key: str):
    """Set bundled keys (called during build process)."""
    global _BUNDLED_KEYS
    _BUNDLED_KEYS["VOYAGE_API_KEY"] = base64.b64encode(voyage_key.encode()).decode()
    _BUNDLED_KEYS["PINECONE_API_KEY"] = base64.b64encode(pinecone_key.encode()).decode()
    _BUNDLED_KEYS["PINECONE_HOST"] = base64.b64encode(pinecone_host.encode()).decode()
    _BUNDLED_KEYS["COHERE_API_KEY"] = base64.b64encode(cohere_key.encode()).decode()

