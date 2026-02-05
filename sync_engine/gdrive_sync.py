"""
Google Drive sync engine using OAuth 2.0 and Drive API v3.
Uses proxy server for OAuth to keep secrets secure.
"""
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import tempfile
import os
import time
import threading
import webbrowser
from urllib.parse import urlencode
from sync_engine.base_sync import BaseSyncEngine


# Configuration - these are safe public identifiers
GOOGLE_CLIENT_ID = '200229085583-tasbpc46mnl4ahs2hj3ouqtmjf1jdnv5.apps.googleusercontent.com'
PROXY_URL = os.environ.get('PROXY_URL', 'https://gnome-production.up.railway.app')


class GoogleDriveSyncEngine(BaseSyncEngine):
    """Sync engine for Google Drive files."""

    def __init__(self, database):
        super().__init__(database, 'Google Drive')
        self.service = None
        self.credentials = None
        # Lock to protect service object from concurrent access during rebuilds
        self._service_lock = threading.Lock()

    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive using OAuth 2.0.

        Returns:
            True if authentication successful
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

            self.logger.info("authenticate() called - checking for stored tokens...")

            # Check if we have stored tokens
            token_data = self.db.get_oauth_token('google_drive')
            self.logger.info(f"Token data from database: {token_data is not None}")

            if token_data:
                self.logger.info(f"Found tokens - access_token: {token_data.get('access_token', '')[:20]}...")
                # Load existing credentials
                self.credentials = Credentials(
                    token=token_data['access_token'],
                    refresh_token=token_data['refresh_token'],
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=GOOGLE_CLIENT_ID,
                    client_secret=None,  # We don't have the secret - refresh via proxy
                    scopes=SCOPES
                )

                # Check if token is expired
                if self.credentials.expired and self.credentials.refresh_token:
                    # Refresh via proxy server
                    if self._refresh_google_token(token_data['refresh_token']):
                        # Reload credentials after refresh
                        token_data = self.db.get_oauth_token('google_drive')
                        self.credentials = Credentials(
                            token=token_data['access_token'],
                            refresh_token=token_data['refresh_token'],
                            token_uri='https://oauth2.googleapis.com/token',
                            client_id=GOOGLE_CLIENT_ID,
                            client_secret=None,
                            scopes=SCOPES
                        )
                    else:
                        # Refresh failed - need to re-authenticate
                        self.logger.warning("Token refresh failed, need to re-authenticate")
                        return False
            else:
                # No tokens - need to authenticate via proxy OAuth
                self.logger.info("No tokens found - starting OAuth flow via proxy")
                return self._start_oauth_flow()

            # Build Drive service
            self.service = build('drive', 'v3', credentials=self.credentials)
            self.logger.info("✅ Google Drive authentication successful")

            # Test the connection
            try:
                about = self.service.about().get(fields="user").execute()
                user_email = about.get('user', {}).get('emailAddress', 'Unknown')
                self.logger.info(f"✅ Connected to Google Drive as: {user_email}")
            except Exception as test_error:
                self.logger.warning(f"Auth succeeded but test failed: {test_error}")

            return True

        except Exception as e:
            self.logger.error(f"❌ Google Drive authentication failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _start_oauth_flow(self) -> bool:
        """
        Start OAuth flow via proxy server.
        Opens browser to Google OAuth, which redirects to proxy for token exchange.
        """
        try:
            # Build the Google OAuth URL that redirects to our proxy
            redirect_uri = f"{PROXY_URL.rstrip('/')}/oauth/google/callback"

            params = {
                'client_id': GOOGLE_CLIENT_ID,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': 'https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/userinfo.email',
                'access_type': 'offline',
                'prompt': 'select_account consent',  # Always show account picker and consent
                'state': 'google_drive'  # Identifies this is for Google Drive
            }

            auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

            self.logger.info(f"Opening browser for Google Drive authentication...")
            webbrowser.open(auth_url)

            # The browser will redirect to proxy, which redirects to localhost:5001/api/oauth/callback
            # The Flask app will handle that and save the tokens
            # Return False for now - the user needs to complete the OAuth flow
            return False

        except Exception as e:
            self.logger.error(f"Failed to start OAuth flow: {e}")
            return False

    def _refresh_google_token(self, refresh_token: str) -> bool:
        """Refresh Google token via proxy server."""
        try:
            import requests

            response = requests.post(
                f"{PROXY_URL.rstrip('/')}/oauth/google/refresh",
                json={'refresh_token': refresh_token},
                timeout=30
            )

            if response.status_code == 200:
                tokens = response.json()
                self.db.save_oauth_token(
                    'google_drive',
                    tokens['access_token'],
                    refresh_token,  # Refresh token doesn't change
                    None
                )
                return True
            else:
                self.logger.error(f"Token refresh failed: {response.text}")
                return False

        except Exception as e:
            self.logger.error(f"Token refresh error: {e}")
            return False

    def complete_oauth(self, tokens: dict) -> bool:
        """
        Complete OAuth flow with tokens received from proxy callback.
        Called by the Flask app after OAuth redirect.
        """
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

            self.logger.info(f"Saving Google Drive OAuth tokens (access_token: {tokens.get('access_token', '')[:20]}...)")

            # Save tokens to database
            self.db.save_oauth_token(
                'google_drive',
                tokens['access_token'],
                tokens.get('refresh_token'),
                None
            )

            self.logger.info("Tokens saved to database, verifying...")

            # Verify tokens were saved
            saved_token = self.db.get_oauth_token('google_drive')
            if not saved_token:
                self.logger.error("CRITICAL: Tokens were NOT saved to database!")
                return False
            self.logger.info("Tokens verified in database ✓")

            # Create credentials
            self.credentials = Credentials(
                token=tokens['access_token'],
                refresh_token=tokens.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=GOOGLE_CLIENT_ID,
                client_secret=None,
                scopes=SCOPES
            )

            # Build Drive service
            self.service = build('drive', 'v3', credentials=self.credentials)
            self.logger.info("✅ Google Drive OAuth completed successfully")

            return True

        except Exception as e:
            self.logger.error(f"Failed to complete OAuth: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def is_authenticated(self) -> bool:
        """Check if Google Drive is authenticated."""
        # Check if we have tokens
        token_data = self.db.get_oauth_token('google_drive')
        return token_data is not None or self.service is not None

    def disconnect(self):
        """Remove Google Drive authentication."""
        self.logger.info("Disconnecting Google Drive...")

        # Close the service first to stop any pending requests
        if self.service:
            try:
                # Close the underlying http connection
                if hasattr(self.service, '_http') and self.service._http:
                    self.service._http.close()
            except Exception as e:
                self.logger.debug(f"Error closing http connection: {e}")

        # Clear credentials and service
        self.credentials = None
        self.service = None

        # Delete tokens from database
        self.db.delete_oauth_token('google_drive')
        self.logger.info("Google Drive disconnected")

    def save_tokens(self):
        """Save OAuth tokens to database."""
        if self.credentials:
            expires_at = None
            if hasattr(self.credentials, 'expiry') and self.credentials.expiry:
                expires_at = self.credentials.expiry.isoformat()

            self.db.save_oauth_token(
                'google_drive',
                self.credentials.token,
                self.credentials.refresh_token,
                expires_at
            )

    def _ensure_fresh_service(self):
        """Rebuild service with fresh SSL connection (thread-safe).

        This prevents stale SSL connections that can cause
        '[SSL] record layer failure' errors after idle periods.

        Uses a lock to prevent concurrent rebuilds which can cause
        heap corruption when one thread closes a connection another is using.
        """
        with self._service_lock:
            from googleapiclient.discovery import build

            # If credentials are not set, load them from database first
            if not self.credentials:
                self.logger.info("Credentials not set, calling authenticate() first...")
                if not self.authenticate():
                    self.logger.error("Cannot rebuild service - authentication failed")
                    return

            # Close existing connection to release SSL resources
            if self.service:
                try:
                    if hasattr(self.service, '_http') and self.service._http:
                        self.service._http.close()
                except Exception as e:
                    self.logger.debug(f"Error closing old connection: {e}")

            # Rebuild service with fresh connection
            self.service = build('drive', 'v3', credentials=self.credentials)
            self.logger.debug("Rebuilt Google Drive service with fresh connection")

    def fetch_files(self) -> List[Dict]:
        """
        Fetch ALL supported files from Google Drive.
        Includes PDFs, Office docs, images, and native Google formats.

        Note: SSL errors are NOT retried mid-operation to prevent heap corruption.
        The _ensure_fresh_service() is called ONCE at the start of this method.
        If SSL errors occur, they propagate up and the next sync will use fresh connections.

        Returns:
            List of file info dicts
        """
        self.logger.info(f"fetch_files() called. self.service={self.service is not None}, self.credentials={self.credentials is not None}")

        if not self.service:
            self.logger.info("Service not initialized, calling authenticate()...")
            if not self.authenticate():
                self.logger.error("Cannot fetch files - authentication failed")
                return []
            self.logger.info(f"After authenticate(): self.service={self.service is not None}")

        # Rebuild service ONCE to prevent stale SSL connections
        self.logger.info("Calling _ensure_fresh_service()...")
        self._ensure_fresh_service()
        self.logger.info("_ensure_fresh_service() complete")

        files = []
        page_token = None
        max_retries = 3

        try:
            # Query for ALL supported file types including native Google formats
            mime_types = [
                # Standard formats
                "mimeType='application/pdf'",
                "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'",  # DOCX
                "mimeType='application/vnd.openxmlformats-officedocument.presentationml.presentation'",  # PPTX
                "mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'",  # XLSX
                "mimeType='application/msword'",  # DOC
                "mimeType='application/vnd.ms-powerpoint'",  # PPT
                "mimeType='application/vnd.ms-excel'",  # XLS
                "mimeType='text/plain'",  # TXT
                "mimeType='text/markdown'",  # MD
                "mimeType='text/csv'",  # CSV
                "mimeType='image/png'",
                "mimeType='image/jpeg'",
                "mimeType='image/jpg'",
                "mimeType='image/gif'",
                "mimeType='image/webp'",
                # Native Google formats (will be exported)
                "mimeType='application/vnd.google-apps.document'",  # Google Docs
                "mimeType='application/vnd.google-apps.spreadsheet'",  # Google Sheets
                "mimeType='application/vnd.google-apps.presentation'",  # Google Slides
            ]
            query = f"({' or '.join(mime_types)}) and trashed=false"

            retries = 0
            while True:
                try:
                    response = self.service.files().list(
                        q=query,
                        spaces='drive',
                        fields='nextPageToken, files(id, name, mimeType, size, modifiedTime, webContentLink, webViewLink)',
                        pageToken=page_token,
                        pageSize=100
                    ).execute()

                    for file in response.get('files', []):
                        # Get file extension and mime type
                        filename = file['name']
                        mime_type = file.get('mimeType', '')
                        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

                        # Handle Google native formats - add appropriate extension
                        if mime_type == 'application/vnd.google-apps.document':
                            if not filename.endswith('.docx'):
                                filename = f"{filename}.docx"
                                ext = 'docx'
                        elif mime_type == 'application/vnd.google-apps.spreadsheet':
                            if not filename.endswith('.xlsx'):
                                filename = f"{filename}.xlsx"
                                ext = 'xlsx'
                        elif mime_type == 'application/vnd.google-apps.presentation':
                            if not filename.endswith('.pptx'):
                                filename = f"{filename}.pptx"
                                ext = 'pptx'

                        files.append({
                            'filename': filename,
                            'file_path': file['id'],  # Use Drive ID as path
                            'file_size': int(file.get('size', 0)),
                            'last_modified': datetime.fromisoformat(file['modifiedTime'].replace('Z', '+00:00')),
                            'file_hash': f"gdrive_{file['id']}",  # Unique hash for cloud files
                            'download_url': file.get('webContentLink'),
                            'metadata': {
                                'drive_id': file['id'],
                                'webUrl': file.get('webViewLink'),  # URL to open in browser
                                'mimeType': mime_type,
                                'extension': f'.{ext}' if ext else '',
                                'is_google_native': mime_type.startswith('application/vnd.google-apps.')
                            }
                        })

                    page_token = response.get('nextPageToken')
                    if not page_token:
                        break

                    retries = 0  # Reset retry counter on success

                except Exception as page_error:
                    if retries < max_retries:
                        retries += 1
                        self.logger.warning(f"Page fetch failed (attempt {retries}/{max_retries}): {page_error}")
                        time.sleep(2 ** retries)  # Exponential backoff
                        continue
                    else:
                        raise  # Give up after max retries

            self.logger.info(f"✅ Fetched {len(files)} files from Google Drive")
            return files

        except Exception as e:
            self.logger.error(f"❌ Failed to fetch Google Drive files: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    def download_file(self, file_info: Dict) -> Optional[Path]:
        """
        Download a file from Google Drive to temp location.
        Handles both regular files and Google native formats (exports them).

        Args:
            file_info: File information from fetch_files()

        Returns:
            Path to downloaded file
        """
        if not self.service:
            return None

        try:
            from googleapiclient.http import MediaIoBaseDownload
            import io

            drive_id = file_info['metadata']['drive_id']
            mime_type = file_info['metadata'].get('mimeType', '')
            is_google_native = file_info['metadata'].get('is_google_native', False)

            # Download to temp file
            temp_dir = Path(tempfile.gettempdir()) / 'gnome_cache'
            temp_dir.mkdir(exist_ok=True)

            # Sanitize filename - replace path separators and other problematic chars
            safe_filename = file_info['filename'].replace('/', '_').replace('\\', '_').replace(':', '_')
            temp_file = temp_dir / safe_filename

            # Handle Google native formats - export instead of download
            if is_google_native:
                # Map Google formats to export MIME types
                export_formats = {
                    'application/vnd.google-apps.document': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # Docs -> DOCX
                    'application/vnd.google-apps.spreadsheet': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # Sheets -> XLSX
                    'application/vnd.google-apps.presentation': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # Slides -> PPTX
                }

                export_mime = export_formats.get(mime_type)
                if export_mime:
                    request = self.service.files().export_media(fileId=drive_id, mimeType=export_mime)
                    self.logger.info(f"Exporting Google native format: {file_info['filename']}")
                else:
                    self.logger.warning(f"Unknown Google format: {mime_type}, trying regular download")
                    request = self.service.files().get_media(fileId=drive_id)
            else:
                # Regular file download
                request = self.service.files().get_media(fileId=drive_id)

            # Download/export the file
            fh = None
            try:
                fh = io.FileIO(str(temp_file), 'wb')
                downloader = MediaIoBaseDownload(fh, request)

                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    self.logger.debug(f"Download {int(status.progress() * 100)}%")

                self.logger.info(f"Downloaded: {file_info['filename']}")
                return temp_file
            finally:
                if fh:
                    fh.close()

        except Exception as e:
            self.logger.error(f"Failed to download {file_info['filename']}: {e}")
            return None
