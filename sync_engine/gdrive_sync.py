"""
Google Drive sync engine using OAuth 2.0 and Drive API v3.
"""
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import tempfile
import os
import time
from sync_engine.base_sync import BaseSyncEngine


class GoogleDriveSyncEngine(BaseSyncEngine):
    """Sync engine for Google Drive files."""
    
    def __init__(self, database):
        super().__init__(database, 'Google Drive')
        self.service = None
        self.credentials = None
    
    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive using OAuth 2.0.
        
        Returns:
            True if authentication successful
        """
        try:
            # Check if OAuth is configured
            client_id = os.environ.get('GOOGLE_CLIENT_ID')
            client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
            
            if not client_id or not client_secret:
                self.logger.warning("Google OAuth not configured (GOOGLE_CLIENT_ID/SECRET missing)")
                return False
            
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            
            SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
            
            # Check if we have stored tokens
            token_data = self.db.get_oauth_token('google_drive')
            
            if token_data:
                # Load existing credentials
                self.credentials = Credentials(
                    token=token_data['access_token'],
                    refresh_token=token_data['refresh_token'],
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=SCOPES
                )
                
                # Refresh if expired
                if self.credentials.expired and self.credentials.refresh_token:
                    self.credentials.refresh(Request())
                    self.save_tokens()
            else:
                # No tokens - need to authenticate
                self.logger.info("Opening browser for Google Drive authentication...")
                flow = InstalledAppFlow.from_client_config(
                    {
                        "installed": {
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "redirect_uris": ["http://localhost:8081/"],
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token"
                        }
                    },
                    SCOPES
                )
                self.credentials = flow.run_local_server(port=0)  # Use port 0 for automatic port selection
                self.save_tokens()
            
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
    
    def is_authenticated(self) -> bool:
        """Check if Google Drive is authenticated."""
        # Check if we have tokens
        token_data = self.db.get_oauth_token('google_drive')
        return token_data is not None or self.service is not None
    
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
    
    def fetch_files(self) -> List[Dict]:
        """
        Fetch PDF files from Google Drive with retry logic.
        
        Returns:
            List of file info dicts
        """
        if not self.service:
            if not self.authenticate():
                self.logger.error("Cannot fetch files - not authenticated")
                return []
        
        files = []
        page_token = None
        max_retries = 3
        
        try:
            # Query for multiple file types (PDFs, docs, images, etc.)
            mime_types = [
                "mimeType='application/pdf'",
                "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'",  # DOCX
                "mimeType='application/vnd.openxmlformats-officedocument.presentationml.presentation'",  # PPTX
                "mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'",  # XLSX
                "mimeType='text/plain'",  # TXT
                "mimeType='text/markdown'",  # MD
                "mimeType='image/png'",
                "mimeType='image/jpeg'"
            ]
            query = f"({' or '.join(mime_types)}) and trashed=false"
            
            retries = 0
            while True:
                try:
                    response = self.service.files().list(
                        q=query,
                        spaces='drive',
                        fields='nextPageToken, files(id, name, size, modifiedTime, webContentLink, webViewLink)',
                        pageToken=page_token,
                        pageSize=100
                    ).execute()
                    
                    for file in response.get('files', []):
                        # Get file extension
                        filename = file['name']
                        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
                        
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
                                'mimeType': file.get('mimeType', ''),
                                'extension': f'.{ext}' if ext else ''
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
            
            self.logger.info(f"✅ Fetched {len(files)} PDFs from Google Drive")
            return files
            
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch Google Drive files: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []
    
    def download_file(self, file_info: Dict) -> Optional[Path]:
        """
        Download a file from Google Drive to temp location.
        
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
            
            # Download to temp file
            temp_dir = Path(tempfile.gettempdir()) / 'gnome_cache'
            temp_dir.mkdir(exist_ok=True)
            
            temp_file = temp_dir / file_info['filename']
            
            request = self.service.files().get_media(fileId=drive_id)
            fh = io.FileIO(str(temp_file), 'wb')
            downloader = MediaIoBaseDownload(fh, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
                self.logger.debug(f"Download {int(status.progress() * 100)}%")
            
            fh.close()
            self.logger.info(f"Downloaded: {file_info['filename']}")
            return temp_file
            
        except Exception as e:
            self.logger.error(f"Failed to download {file_info['filename']}: {e}")
            return None

