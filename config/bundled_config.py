"""
Bundled API configuration for Gnome.
This file contains obfuscated API keys for out-of-the-box functionality.
"""
import base64
import os

# Obfuscated API keys (Base64 encoded)
_BUNDLED_KEYS = {
    "VOYAGE_API_KEY": "cGEtMnE4WXFWTkcwWVBYV3REZnRVVHk2dWlyQXlJZFN5UTVFOGV1dEhPM1ZCSQ==",
    "PINECONE_API_KEY": "cGNza195NG9pVl9UWTNYdWd5Mk1peUNvWjVBOWpxZVdQUkhOU05pd3pEVGFyWlYzSkNCSjVyR2p6dHJjNTlxcFB5cThCM0hMQVg=",
    "PINECONE_HOST": "aHR0cHM6Ly92b3lhZ2UtbXVsdGltb2RhbC0zLThkb3kzMmUuc3ZjLmFwZWQtNDYyNy1iNzRhLnBpbmVjb25lLmlv",
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
