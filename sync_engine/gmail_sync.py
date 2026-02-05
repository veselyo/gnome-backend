"""
Gmail Sync Engine for Gnome
Indexes email attachments via Gmail API
Uses proxy server for OAuth to keep secrets secure.
"""

import os
import base64
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Generator
from pathlib import Path
import hashlib
import json
import re
import logging
import webbrowser
from urllib.parse import urlencode

from database.models import (
    GnomeDatabase, get_db_connection, upsert_file,
    get_oauth_token, save_oauth_token, delete_oauth_token
)
from sync_engine.base_sync import BaseSyncEngine

logger = logging.getLogger(__name__)

# Configuration - these are safe public identifiers
GOOGLE_CLIENT_ID = '200229085583-tasbpc46mnl4ahs2hj3ouqtmjf1jdnv5.apps.googleusercontent.com'
PROXY_URL = os.environ.get('PROXY_URL', 'https://gnome-production.up.railway.app')

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
]


class GmailSyncEngine(BaseSyncEngine):
    """Sync engine for Gmail emails and attachments."""

    def __init__(self, database: GnomeDatabase):
        super().__init__(database, 'Gmail')
        self.service = None
        self.credentials = None
        self.user_email = ''
        self.attachment_dir = Path.home() / ".gnome" / "gmail_attachments"
        self.attachment_dir.mkdir(parents=True, exist_ok=True)
        # Lock to protect service object from concurrent access during rebuilds
        self._service_lock = threading.Lock()

    def authenticate(self) -> bool:
        """Authenticate with Gmail using OAuth via proxy."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            # Check for stored tokens
            token_data = get_oauth_token('gmail')

            if token_data:
                self.credentials = Credentials(
                    token=token_data['access_token'],
                    refresh_token=token_data.get('refresh_token'),
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=GOOGLE_CLIENT_ID,
                    client_secret=None,  # No secret - refresh via proxy
                    scopes=SCOPES
                )

                # Load stored user email
                self.user_email = token_data.get('user_email', '')

                if self.credentials.expired and self.credentials.refresh_token:
                    # Refresh via proxy server
                    if self._refresh_google_token(token_data['refresh_token']):
                        # Reload credentials after refresh
                        token_data = get_oauth_token('gmail')
                        self.credentials = Credentials(
                            token=token_data['access_token'],
                            refresh_token=token_data.get('refresh_token'),
                            token_uri='https://oauth2.googleapis.com/token',
                            client_id=GOOGLE_CLIENT_ID,
                            client_secret=None,
                            scopes=SCOPES
                        )
                    else:
                        self.logger.warning("Token refresh failed, need to re-authenticate")
                        return False
            else:
                # No tokens - need to authenticate via proxy OAuth
                self.logger.info("No tokens found - starting OAuth flow via proxy")
                return self._start_oauth_flow()

            self.service = build('gmail', 'v1', credentials=self.credentials)

            # Get and store the user's email address if not already stored
            if not self.user_email:
                try:
                    profile = self.service.users().getProfile(userId='me').execute()
                    self.user_email = profile.get('emailAddress', '')
                    self._save_credentials()
                except Exception as e:
                    self.logger.warning(f"Could not get user email: {e}")

            self.logger.info(f"Gmail authentication successful for {self.user_email}")
            return True

        except Exception as e:
            self.logger.error(f"Gmail authentication failed: {e}")
            return False

    def _start_oauth_flow(self) -> bool:
        """Start OAuth flow via proxy server."""
        try:
            redirect_uri = f"{PROXY_URL.rstrip('/')}/oauth/google/callback"

            params = {
                'client_id': GOOGLE_CLIENT_ID,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email',
                'access_type': 'offline',
                'prompt': 'select_account consent',
                'state': 'gmail'
            }

            auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

            self.logger.info("Opening browser for Gmail authentication...")
            webbrowser.open(auth_url)

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
                save_oauth_token(
                    service='gmail',
                    access_token=tokens['access_token'],
                    refresh_token=refresh_token,
                    expires_at=None,
                    extra_data={'user_email': self.user_email}
                )
                return True
            else:
                self.logger.error(f"Token refresh failed: {response.text}")
                return False

        except Exception as e:
            self.logger.error(f"Token refresh error: {e}")
            return False

    def complete_oauth(self, tokens: dict) -> bool:
        """Complete OAuth flow with tokens from proxy callback."""
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            self.user_email = tokens.get('email', '')
            self.logger.info(f"Saving Gmail OAuth tokens for {self.user_email}...")

            save_oauth_token(
                service='gmail',
                access_token=tokens['access_token'],
                refresh_token=tokens.get('refresh_token'),
                expires_at=None,
                extra_data={'user_email': self.user_email}
            )

            self.logger.info("Tokens saved, verifying...")

            # Verify tokens were saved
            saved_token = get_oauth_token('gmail')
            if not saved_token:
                self.logger.error("CRITICAL: Gmail tokens were NOT saved to database!")
                return False
            self.logger.info("Gmail tokens verified in database ✓")

            self.credentials = Credentials(
                token=tokens['access_token'],
                refresh_token=tokens.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=GOOGLE_CLIENT_ID,
                client_secret=None,
                scopes=SCOPES
            )

            self.service = build('gmail', 'v1', credentials=self.credentials)
            self.logger.info(f"✅ Gmail OAuth completed successfully for {self.user_email}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to complete OAuth: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _save_credentials(self):
        """Save credentials to database."""
        if self.credentials:
            expires_at = None
            if hasattr(self.credentials, 'expiry') and self.credentials.expiry:
                expires_at = self.credentials.expiry.isoformat()

            extra_data = {'user_email': self.user_email}

            save_oauth_token(
                service='gmail',
                access_token=self.credentials.token,
                refresh_token=self.credentials.refresh_token,
                expires_at=expires_at,
                extra_data=extra_data
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
            self.service = build('gmail', 'v1', credentials=self.credentials)
            self.logger.debug("Rebuilt Gmail service with fresh connection")

    def disconnect(self):
        """Remove Gmail authentication."""
        self.logger.info("Disconnecting Gmail...")

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
        self.user_email = ''

        # Delete tokens from database
        delete_oauth_token('gmail')
        self.logger.info("Gmail disconnected")

    def is_authenticated(self) -> bool:
        """Check if authenticated."""
        if self.service:
            return True
        token_data = get_oauth_token('gmail')
        return token_data is not None

    def fetch_files(self) -> List[Dict]:
        """Fetch emails as 'files' - not used, sync handles directly."""
        return []

    def download_file(self, file_info: Dict) -> Optional[Path]:
        """Download attachment - used internally."""
        return None

    def _fetch_emails(
        self,
        query: str = "",
        max_results: int = 500,
        after_date: Optional[datetime] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """Fetch emails matching query.

        Note: SSL errors are NOT retried mid-operation to prevent heap corruption.
        The _ensure_fresh_service() is called ONCE at the start of sync() instead.
        If SSL errors occur, they propagate up and the next sync will use fresh connections.
        """
        if not self.service:
            if not self.authenticate():
                return

        search_query = query
        if after_date:
            date_str = after_date.strftime("%Y/%m/%d")
            search_query = f"{search_query} after:{date_str}".strip()

        try:
            page_token = None
            fetched = 0

            while fetched < max_results:
                response = self.service.users().messages().list(
                    userId='me',
                    q=search_query,
                    maxResults=min(100, max_results - fetched),
                    pageToken=page_token
                ).execute()

                messages = response.get('messages', [])
                if not messages:
                    break

                for msg_data in messages:
                    try:
                        msg = self.service.users().messages().get(
                            userId='me',
                            id=msg_data['id'],
                            format='full'
                        ).execute()

                        yield self._parse_message(msg)
                        fetched += 1

                        if fetched >= max_results:
                            break

                    except Exception as e:
                        self.logger.warning(f"Error fetching message {msg_data['id']}: {e}")

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

        except Exception as e:
            self.logger.error(f"Gmail API error: {e}")

    def _parse_message(self, message: Dict) -> Dict[str, Any]:
        """Parse Gmail API message into structured data."""
        headers = {h['name']: h['value'] for h in message['payload'].get('headers', [])}

        result = {
            "id": message['id'],
            "thread_id": message['threadId'],
            "subject": headers.get('Subject', '(No Subject)'),
            "from": headers.get('From', ''),
            "to": headers.get('To', ''),
            "date": headers.get('Date', ''),
            "snippet": message.get('snippet', ''),
            "body": "",
            "attachments": []
        }

        # Extract body
        result["body"] = self._extract_body(message['payload'])

        # Extract attachments
        result["attachments"] = self._extract_attachments(message['id'], message['payload'])

        return result

    def _extract_body(self, payload: Dict) -> str:
        """Extract email body text from payload."""
        body = ""

        if 'body' in payload and payload['body'].get('data'):
            try:
                body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
            except:
                pass

        elif 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')

                if mime_type == 'text/plain':
                    if part.get('body', {}).get('data'):
                        try:
                            body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                            break
                        except:
                            pass

                elif mime_type == 'text/html' and not body:
                    if part.get('body', {}).get('data'):
                        try:
                            html = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                            body = re.sub(r'<[^>]+>', ' ', html)
                            body = re.sub(r'\s+', ' ', body).strip()
                        except:
                            pass

                elif 'parts' in part:
                    nested_body = self._extract_body(part)
                    if nested_body:
                        body = nested_body
                        break

        return body

    def _extract_attachments(self, message_id: str, payload: Dict) -> List[Dict[str, Any]]:
        """Extract attachment metadata."""
        attachments = []

        def process_parts(parts):
            for part in parts:
                filename = part.get('filename', '')
                if filename and part.get('body', {}).get('attachmentId'):
                    attachments.append({
                        "filename": filename,
                        "mime_type": part.get('mimeType', ''),
                        "size": part.get('body', {}).get('size', 0),
                        "attachment_id": part['body']['attachmentId'],
                        "message_id": message_id
                    })

                if 'parts' in part:
                    process_parts(part['parts'])

        if 'parts' in payload:
            process_parts(payload['parts'])

        return attachments

    def download_attachment(self, message_id: str, attachment_id: str, filename: str) -> Optional[str]:
        """Download an attachment and save to local storage."""
        try:
            attachment = self.service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=attachment_id
            ).execute()

            data = base64.urlsafe_b64decode(attachment['data'])

            safe_filename = "".join(c for c in filename if c.isalnum() or c in '.-_')
            file_path = self.attachment_dir / f"{message_id}_{safe_filename}"

            with open(file_path, 'wb') as f:
                f.write(data)

            return str(file_path)

        except Exception as e:
            self.logger.error(f"Error downloading attachment: {e}")
            return None

    def sync(
        self,
        search_engine=None,
        max_files: int = 500,
        days_back: int = 90
    ) -> Dict[str, int]:
        """Sync Gmail attachments to search index (attachments only, not email content)."""
        from semantic_search.search_engine import get_search_engine
        from semantic_search.file_processor import extract_text

        if search_engine is None:
            search_engine = get_search_engine()

        # If search engine is still None (cloud not configured), track files but don't index
        if search_engine is None:
            self.logger.warning("Search engine not available - tracking files only, not indexing")

        if not self.is_authenticated():
            if not self.authenticate():
                raise RuntimeError("Gmail not authenticated")

        # Rebuild service to prevent stale SSL connections
        self._ensure_fresh_service()

        stats = {"indexed": 0, "skipped": 0, "errors": 0, "total": 0}

        # Get already indexed attachment hashes
        indexed_hashes = set()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT file_hash FROM files WHERE source = ?", (self.source_name,))
        indexed_hashes = {row[0] for row in cursor.fetchall()}
        # Don't close - using thread-local connections

        batch = []
        batch_size = 50
        emails_checked = 0

        after_date = datetime.now() - timedelta(days=days_back)

        # Only fetch emails that have attachments
        for email_data in self._fetch_emails(query="has:attachment", after_date=after_date, max_results=max_files * 2):
            emails_checked += 1

            # Stop if we've indexed enough attachments
            if stats["indexed"] >= max_files:
                break

            try:
                # Only process attachments, skip email content
                for att in email_data.get('attachments', []):
                    if stats["indexed"] >= max_files:
                        break

                    stats["total"] += 1

                    try:
                        att_id = hashlib.sha256(f"gmail_att:{att['attachment_id']}".encode()).hexdigest()

                        if att_id in indexed_hashes:
                            stats["skipped"] += 1
                            continue

                        local_path = self.download_attachment(
                            att['message_id'],
                            att['attachment_id'],
                            att['filename']
                        )

                        if local_path:
                            att_content = extract_text(local_path)

                            if att_content and len(att_content) > 20:
                                # Get the account email for opening the correct account
                                account_email = self.user_email or ''
                                if not account_email:
                                    token_data = get_oauth_token('gmail')
                                    if token_data:
                                        account_email = token_data.get('user_email', '')

                                att_metadata = {
                                    "filename": att['filename'],
                                    "source": self.source_name,
                                    "file_path": local_path,
                                    "type": "attachment",
                                    "parent_email": email_data['subject'][:100] if email_data['subject'] else "(No Subject)",
                                    "from": email_data['from'][:200] if email_data['from'] else "",
                                    "date": email_data['date'],
                                    "gmail_message_id": email_data['id'],
                                    "account_email": account_email
                                }

                                batch.append({
                                    "id": att_id,
                                    "content": att_content,
                                    "metadata": att_metadata
                                })

                                upsert_file(
                                    filename=att['filename'],
                                    file_path=local_path,
                                    source=self.source_name,
                                    file_hash=att_id,
                                    pinecone_id=att_id,
                                    metadata=json.dumps(att_metadata)
                                )

                                stats["indexed"] += 1

                    except Exception as e:
                        self.logger.warning(f"Error processing attachment {att.get('filename', 'unknown')}: {e}")
                        stats["errors"] += 1

                if len(batch) >= batch_size and search_engine:
                    search_engine.index_batch(batch)
                    batch = []
                    self.logger.info(f"Indexed {stats['indexed']} Gmail attachments...")

            except Exception as e:
                self.logger.error(f"Error processing email attachments: {e}")
                stats["errors"] += 1

        # Index remaining batch
        if batch and search_engine:
            search_engine.index_batch(batch)

        self.logger.info(f"Gmail sync complete: checked {emails_checked} emails, {stats}")
        return stats
