"""
Google Drive sync engine using OAuth 2.0 and Drive API v3.
"""
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import tempfile
import os
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
                            "redirect_uris": ["http://localhost:8080/"],
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token"
                        }
                    },
                    SCOPES
                )
                self.credentials = flow.run_local_server(port=8080)
                self.save_tokens()
            
            # Build Drive service
            self.service = build('drive', 'v3', credentials=self.credentials)
            self.logger.info("✅ Google Drive authentication successful")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Google Drive authentication failed: {e}")
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
        Fetch PDF files from Google Drive.
        
        Returns:
            List of file info dicts
        """
        if not self.service:
            if not self.authenticate():
                return []
        
        files = []
        page_token = None
        
        # Get last sync cursor for incremental sync
        sync_state = self.db.get_sync_state('Google Drive')
        if sync_state and sync_state.get('cursor'):
            page_token = sync_state['cursor']
        
        try:
            # Query for PDF files
            query = "mimeType='application/pdf' and trashed=false"
            
            while True:
                response = self.service.files().list(
                    q=query,
                    spaces='drive',
                    fields='nextPageToken, files(id, name, size, modifiedTime, webContentLink)',
                    pageToken=page_token,
                    pageSize=100
                ).execute()
                
                for file in response.get('files', []):
                    files.append({
                        'filename': file['name'],
                        'file_path': file['id'],  # Use Drive ID as path
                        'file_size': int(file.get('size', 0)),
                        'last_modified': datetime.fromisoformat(file['modifiedTime'].replace('Z', '+00:00')),
                        'file_hash': file['id'],  # Use ID as hash for cloud files
                        'download_url': file.get('webContentLink'),
                        'metadata': {
                            'drive_id': file['id']
                        }
                    })
                
                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            
            self.logger.info(f"Fetched {len(files)} PDFs from Google Drive")
            return files
            
        except Exception as e:
            self.logger.error(f"Failed to fetch Google Drive files: {e}")
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

