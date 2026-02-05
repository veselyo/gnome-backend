"""
OneDrive sync engine using Microsoft Graph API.
Uses proxy server for OAuth to keep secrets secure.
"""
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import tempfile
import os
import time
import webbrowser
import requests
from urllib.parse import urlencode
from sync_engine.base_sync import BaseSyncEngine
from database.models import get_oauth_token, save_oauth_token, delete_oauth_token


# Configuration - these are safe public identifiers
MICROSOFT_CLIENT_ID = '9ff39189-1c55-4b23-8cb2-fdeebffe1d70'
PROXY_URL = os.environ.get('PROXY_URL', 'https://gnome-production.up.railway.app')

# Microsoft Graph API endpoints
AUTH_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0"

# Scopes needed for OneDrive
SCOPES = [
    "offline_access",
    "Files.Read.All",
    "User.Read"  # For getting email
]


class OneDriveSyncEngine(BaseSyncEngine):
    """Sync engine for OneDrive files."""

    def __init__(self, database):
        super().__init__(database, 'OneDrive')
        self.access_token = None
        self.refresh_token = None
        self.user_email = ''
        self.graph_endpoint = 'https://graph.microsoft.com/v1.0'

    def get_auth_url(self) -> str:
        """Get OAuth authorization URL that redirects to proxy."""
        redirect_uri = f"{PROXY_URL.rstrip('/')}/oauth/microsoft/callback"

        params = {
            "client_id": MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "response_mode": "query",
            "state": "onedrive"
        }

        return f"{AUTH_BASE}/authorize?{urlencode(params)}"

    def authenticate(self) -> bool:
        """Load existing tokens or start OAuth flow."""
        self.logger.info("authenticate() called - checking for stored tokens...")
        token_data = get_oauth_token("onedrive")
        self.logger.info(f"Token data from database: {token_data is not None}")

        if not token_data:
            # No tokens - need to authenticate via proxy OAuth
            self.logger.info("No tokens found - starting OAuth flow via proxy")
            return self._start_oauth_flow()

        self.logger.info(f"Found tokens - access_token: {token_data.get('access_token', '')[:20]}...")
        self.access_token = token_data.get("access_token")
        self.refresh_token = token_data.get("refresh_token")
        self.user_email = token_data.get("user_email", "")
        expires_at = token_data.get("expires_at")

        # Check if expired
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if exp_dt < datetime.now():
                    return self._refresh_tokens()
            except:
                pass

        return self.access_token is not None

    def _start_oauth_flow(self) -> bool:
        """Start OAuth flow via proxy server."""
        try:
            auth_url = self.get_auth_url()
            self.logger.info("Opening browser for OneDrive authentication...")
            webbrowser.open(auth_url)
            return False

        except Exception as e:
            self.logger.error(f"Failed to start OAuth flow: {e}")
            return False

    def _refresh_tokens(self) -> bool:
        """Refresh access token via proxy server."""
        if not self.refresh_token:
            return False

        try:
            response = requests.post(
                f"{PROXY_URL.rstrip('/')}/oauth/microsoft/refresh",
                json={'refresh_token': self.refresh_token},
                timeout=30
            )

            if response.status_code == 200:
                tokens = response.json()
                self.access_token = tokens["access_token"]
                self.refresh_token = tokens.get("refresh_token", self.refresh_token)

                expires_in = tokens.get("expires_in", 3600)
                expires_at = datetime.now() + timedelta(seconds=expires_in)

                save_oauth_token(
                    service="onedrive",
                    access_token=self.access_token,
                    refresh_token=self.refresh_token,
                    expires_at=expires_at.isoformat(),
                    extra_data={'user_email': self.user_email}
                )
                return True

            self.logger.error(f"Token refresh failed: {response.text}")
            return False

        except Exception as e:
            self.logger.error(f"Token refresh error: {e}")
            return False

    def complete_oauth(self, tokens: dict) -> bool:
        """Complete OAuth flow with tokens from proxy callback."""
        try:
            self.access_token = tokens["access_token"]
            self.refresh_token = tokens.get("refresh_token")
            self.user_email = tokens.get("email", "")

            self.logger.info(f"Saving OneDrive OAuth tokens for {self.user_email}...")

            expires_in = tokens.get("expires_in", 3600)
            expires_at = datetime.now() + timedelta(seconds=int(expires_in))

            save_oauth_token(
                service="onedrive",
                access_token=self.access_token,
                refresh_token=self.refresh_token,
                expires_at=expires_at.isoformat(),
                extra_data={'user_email': self.user_email}
            )

            # Verify tokens were saved
            saved_token = get_oauth_token('onedrive')
            if not saved_token:
                self.logger.error("CRITICAL: OneDrive tokens were NOT saved to database!")
                return False
            self.logger.info("OneDrive tokens verified in database ✓")

            self.logger.info(f"✅ OneDrive OAuth completed successfully for {self.user_email}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to complete OAuth: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def disconnect(self):
        """Remove OneDrive authentication."""
        self.logger.info("Disconnecting OneDrive...")

        # Clear tokens first (stops any new requests)
        self.access_token = None
        self.refresh_token = None
        self.user_email = ''

        # Delete tokens from database
        delete_oauth_token("onedrive")
        self.logger.info("OneDrive disconnected")

    def is_authenticated(self) -> bool:
        """Check if OneDrive is authenticated."""
        if self.access_token:
            return True
        token_data = get_oauth_token("onedrive")
        return token_data is not None

    def fetch_files(self) -> List[Dict]:
        """
        Fetch PDF files from OneDrive with retry logic and better error handling.

        Returns:
            List of file info dicts
        """
        self.logger.info(f"fetch_files() called. access_token={self.access_token is not None}")

        if not self.access_token:
            self.logger.info("No access_token, calling authenticate()...")
            if not self.authenticate():
                self.logger.error("Cannot fetch files - authentication failed")
                return []
            self.logger.info(f"After authenticate(): access_token={self.access_token is not None}")

        files = []
        next_link = f"{self.graph_endpoint}/me/drive/root/search(q='.pdf')"
        max_retries = 3

        try:
            page_count = 0
            while next_link and page_count < 100:  # Safety limit: max 100 pages
                headers = {'Authorization': f'Bearer {self.access_token}'}

                retries = 0
                while retries <= max_retries:
                    try:
                        response = requests.get(next_link, headers=headers, timeout=30)

                        if response.status_code == 401:
                            # Token expired, re-authenticate
                            self.logger.info("Token expired, re-authenticating...")
                            if self._refresh_tokens():
                                headers = {'Authorization': f'Bearer {self.access_token}'}
                                continue  # Retry with new token
                            else:
                                return files  # Can't auth, return what we have

                        if response.status_code != 200:
                            self.logger.error(f"OneDrive API error: {response.status_code} - {response.text[:200]}")
                            if retries < max_retries:
                                retries += 1
                                time.sleep(2 ** retries)
                                continue
                            else:
                                break  # Give up on this page

                        # Success!
                        data = response.json()

                        for item in data.get('value', []):
                            # Only process PDF files
                            if item.get('file') and item['name'].lower().endswith('.pdf'):
                                files.append({
                                    'filename': item['name'],
                                    'file_path': item['id'],  # Use OneDrive ID
                                    'file_size': item.get('size', 0),
                                    'last_modified': datetime.fromisoformat(item['lastModifiedDateTime'].replace('Z', '+00:00')),
                                    'file_hash': f"onedrive_{item['id']}",  # Unique hash
                                    'download_url': item.get('webUrl', ''),
                                    'metadata': {
                                        'onedrive_id': item['id'],
                                        # Ensure no null values - Pinecone rejects them
                                        'download_link': item.get('@microsoft.graph.downloadUrl') or '',
                                        'webUrl': item.get('webUrl') or ''
                                    }
                                })

                        next_link = data.get('@odata.nextLink')
                        page_count += 1
                        break  # Success, exit retry loop

                    except requests.exceptions.Timeout as timeout_error:
                        if retries < max_retries:
                            retries += 1
                            self.logger.warning(f"Timeout (attempt {retries}/{max_retries}): {timeout_error}")
                            time.sleep(2 ** retries)
                            continue
                        else:
                            self.logger.error("Max retries exceeded due to timeouts")
                            return files  # Return what we have

                    except Exception as page_error:
                        if retries < max_retries:
                            retries += 1
                            self.logger.warning(f"Page error (attempt {retries}/{max_retries}): {page_error}")
                            time.sleep(2 ** retries)
                            continue
                        else:
                            raise

            self.logger.info(f"Fetched {len(files)} PDFs from OneDrive")
            return files

        except Exception as e:
            self.logger.error(f"Failed to fetch OneDrive files: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    def download_file(self, file_info: Dict) -> Optional[Path]:
        """
        Download a file from OneDrive to temp location.

        Args:
            file_info: File information from fetch_files()

        Returns:
            Path to downloaded file
        """
        try:
            download_url = file_info['metadata'].get('download_link')
            if not download_url:
                # Fetch download URL
                headers = {'Authorization': f'Bearer {self.access_token}'}
                onedrive_id = file_info['metadata']['onedrive_id']
                url = f"{self.graph_endpoint}/me/drive/items/{onedrive_id}/content"
                response = requests.get(url, headers=headers, allow_redirects=True)

                if response.status_code != 200:
                    self.logger.error(f"Failed to download: {response.status_code}")
                    return None

                content = response.content
            else:
                # Use direct download link
                response = requests.get(download_url)
                content = response.content

            # Save to temp file
            temp_dir = Path(tempfile.gettempdir()) / 'gnome_cache'
            temp_dir.mkdir(exist_ok=True)
            # Sanitize filename - replace path separators and other problematic chars
            safe_filename = file_info['filename'].replace('/', '_').replace('\\', '_').replace(':', '_')
            temp_file = temp_dir / safe_filename

            with open(temp_file, 'wb') as f:
                f.write(content)

            self.logger.info(f"Downloaded: {file_info['filename']}")
            return temp_file

        except Exception as e:
            self.logger.error(f"Failed to download {file_info['filename']}: {e}")
            return None
