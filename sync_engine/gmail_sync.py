"""
Gmail attachment sync engine.
Downloads and indexes email attachments (perfect for law firms).
"""
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import tempfile
import os
import base64
from sync_engine.base_sync import BaseSyncEngine


class GmailSyncEngine(BaseSyncEngine):
    """Sync engine for Gmail email attachments."""
    
    def __init__(self, database):
        super().__init__(database, 'Gmail')
        self.service = None
        self.credentials = None
    
    def authenticate(self) -> bool:
        """
        Authenticate with Gmail using existing Google OAuth.
        Reuses the same credentials as Google Drive.
        
        Returns:
            True if authentication successful
        """
        try:
            # Check if OAuth is configured
            client_id = os.environ.get('GOOGLE_CLIENT_ID')
            client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
            
            if not client_id or not client_secret:
                self.logger.warning("Google OAuth not configured")
                return False
            
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            
            # Gmail requires additional scopes
            SCOPES = [
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.modify'  # For marking as read
            ]
            
            # Check if we have stored tokens
            token_data = self.db.get_oauth_token('gmail')
            
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
                self.logger.info("Opening browser for Gmail authentication...")
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
                self.credentials = flow.run_local_server(port=0)
                self.save_tokens()
            
            # Build Gmail service
            self.service = build('gmail', 'v1', credentials=self.credentials)
            self.logger.info("✅ Gmail authentication successful")
            
            # Test the connection
            try:
                profile = self.service.users().getProfile(userId='me').execute()
                email = profile.get('emailAddress', 'Unknown')
                self.logger.info(f"✅ Connected to Gmail as: {email}")
            except Exception as test_error:
                self.logger.warning(f"Auth succeeded but test failed: {test_error}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Gmail authentication failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    def is_authenticated(self) -> bool:
        """Check if Gmail is authenticated."""
        token_data = self.db.get_oauth_token('gmail')
        return token_data is not None or self.service is not None
    
    def save_tokens(self):
        """Save OAuth tokens to database."""
        if self.credentials:
            expires_at = None
            if hasattr(self.credentials, 'expiry') and self.credentials.expiry:
                expires_at = self.credentials.expiry.isoformat()
            
            self.db.save_oauth_token(
                'gmail',
                self.credentials.token,
                self.credentials.refresh_token,
                expires_at
            )
    
    def fetch_files(self) -> List[Dict]:
        """
        Fetch email attachments from Gmail.
        Filters for documents (PDFs, DOC, etc.) from last 90 days.
        
        Returns:
            List of attachment info dicts
        """
        if not self.service:
            if not self.authenticate():
                self.logger.error("Cannot fetch attachments - not authenticated")
                return []
        
        attachments = []
        
        try:
            # Query for emails with attachments (last 90 days, important file types)
            query = 'has:attachment (filename:pdf OR filename:docx OR filename:pptx OR filename:xlsx) newer_than:90d'
            
            # Get message list
            response = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=100  # Limit to recent 100 emails
            ).execute()
            
            messages = response.get('messages', [])
            self.logger.info(f"📧 Found {len(messages)} emails with attachments")
            
            for msg_data in messages:
                try:
                    # Get full message
                    msg = self.service.users().messages().get(
                        userId='me',
                        id=msg_data['id'],
                        format='full'
                    ).execute()
                    
                    # Extract attachments
                    for part in msg['payload'].get('parts', []):
                        if part.get('filename') and part.get('body', {}).get('attachmentId'):
                            filename = part['filename']
                            
                            # Filter for supported file types
                            if not self._is_supported_attachment(filename):
                                continue
                            
                            # Get email date
                            date_header = next((h['value'] for h in msg['payload']['headers'] if h['name'] == 'Date'), None)
                            email_date = self._parse_email_date(date_header) if date_header else datetime.now()
                            
                            # Get sender
                            sender = next((h['value'] for h in msg['payload']['headers'] if h['name'] == 'From'), 'Unknown')
                            
                            attachments.append({
                                'filename': filename,
                                'file_path': f"{msg_data['id']}_{part['body']['attachmentId']}",  # Unique ID
                                'file_size': part['body'].get('size', 0),
                                'last_modified': email_date,
                                'file_hash': f"gmail_{msg_data['id']}_{part['body']['attachmentId']}",
                                'metadata': {
                                    'message_id': msg_data['id'],
                                    'attachment_id': part['body']['attachmentId'],
                                    'sender': sender,
                                    'email_date': email_date.isoformat(),
                                    'mime_type': part.get('mimeType', '')
                                }
                            })
                
                except Exception as msg_error:
                    self.logger.warning(f"Failed to process message: {msg_error}")
                    continue
            
            self.logger.info(f"✅ Found {len(attachments)} attachments")
            return attachments
            
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch Gmail attachments: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []
    
    def download_file(self, file_info: Dict) -> Optional[Path]:
        """
        Download email attachment from Gmail.
        
        Args:
            file_info: Attachment information from fetch_files()
        
        Returns:
            Path to downloaded file
        """
        if not self.service:
            return None
        
        try:
            message_id = file_info['metadata']['message_id']
            attachment_id = file_info['metadata']['attachment_id']
            
            # Download to temp file
            temp_dir = Path(tempfile.gettempdir()) / 'gnome_cache' / 'gmail'
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            temp_file = temp_dir / file_info['filename']
            
            # Get attachment data
            attachment = self.service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=attachment_id
            ).execute()
            
            # Decode base64 data
            file_data = base64.urlsafe_b64decode(attachment['data'])
            
            # Write to file
            with open(temp_file, 'wb') as f:
                f.write(file_data)
            
            self.logger.info(f"📥 Downloaded: {file_info['filename']}")
            return temp_file
            
        except Exception as e:
            self.logger.error(f"Failed to download {file_info['filename']}: {e}")
            return None
    
    def _is_supported_attachment(self, filename: str) -> bool:
        """Check if attachment is a supported file type."""
        ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
        supported = ['pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'txt', 'csv']
        return ext in supported
    
    def _parse_email_date(self, date_str: str) -> datetime:
        """Parse email date header."""
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str)
        except:
            return datetime.now()

