"""
Outlook Sync Engine for Gnome
Uses Microsoft Graph API to index email attachments
Uses proxy server for OAuth to keep secrets secure.
"""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Generator
import hashlib
import json
import base64
import webbrowser
import requests
import logging
from pathlib import Path
from urllib.parse import urlencode

from database.models import (
    GnomeDatabase, get_db_connection, upsert_file,
    get_oauth_token, save_oauth_token, delete_oauth_token
)
from sync_engine.base_sync import BaseSyncEngine

logger = logging.getLogger(__name__)

# Configuration - these are safe public identifiers
MICROSOFT_CLIENT_ID = '9ff39189-1c55-4b23-8cb2-fdeebffe1d70'
PROXY_URL = os.environ.get('PROXY_URL', 'https://gnome-production.up.railway.app')

# Microsoft Graph API endpoints
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTH_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0"

# Scopes needed for Outlook
SCOPES = [
    "offline_access",
    "Mail.Read",
    "Calendars.Read",
    "User.Read"  # For getting email
]


class OutlookSyncEngine(BaseSyncEngine):
    """Sync engine for Microsoft Outlook via Graph API."""

    def __init__(self, database: GnomeDatabase):
        super().__init__(database, 'Outlook')
        self.access_token = None
        self.refresh_token = None
        self.user_email = ''
        self.attachment_dir = Path.home() / ".gnome" / "outlook_attachments"
        self.attachment_dir.mkdir(parents=True, exist_ok=True)

    def get_auth_url(self) -> str:
        """Get OAuth authorization URL that redirects to proxy."""
        redirect_uri = f"{PROXY_URL.rstrip('/')}/oauth/microsoft/callback"

        params = {
            "client_id": MICROSOFT_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "response_mode": "query",
            "state": "outlook"
        }

        return f"{AUTH_BASE}/authorize?{urlencode(params)}"

    def authenticate(self) -> bool:
        """Load existing tokens or start OAuth flow."""
        token_data = get_oauth_token("outlook")

        if not token_data:
            # No tokens - need to authenticate via proxy OAuth
            self.logger.info("No tokens found - starting OAuth flow via proxy")
            return self._start_oauth_flow()

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
            self.logger.info("Opening browser for Outlook authentication...")
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
                    service="outlook",
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

            self.logger.info(f"Saving Outlook OAuth tokens for {self.user_email}...")

            expires_in = tokens.get("expires_in", 3600)
            expires_at = datetime.now() + timedelta(seconds=int(expires_in))

            save_oauth_token(
                service="outlook",
                access_token=self.access_token,
                refresh_token=self.refresh_token,
                expires_at=expires_at.isoformat(),
                extra_data={'user_email': self.user_email}
            )

            # Verify tokens were saved
            saved_token = get_oauth_token('outlook')
            if not saved_token:
                self.logger.error("CRITICAL: Outlook tokens were NOT saved to database!")
                return False
            self.logger.info("Outlook tokens verified in database ✓")

            self.logger.info(f"✅ Outlook OAuth completed successfully for {self.user_email}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to complete OAuth: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _get_user_email(self) -> str:
        """Get the authenticated user's email address."""
        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = requests.get(f"{GRAPH_BASE}/me", headers=headers)
            if response.status_code == 200:
                user_data = response.json()
                return user_data.get('mail') or user_data.get('userPrincipalName', '')
        except Exception as e:
            self.logger.warning(f"Could not get user email: {e}")
        return ''

    def disconnect(self):
        """Remove Outlook authentication."""
        self.logger.info("Disconnecting Outlook...")

        # Clear tokens first (stops any new requests)
        self.access_token = None
        self.refresh_token = None
        self.user_email = ''

        # Delete tokens from database
        delete_oauth_token("outlook")
        self.logger.info("Outlook disconnected")

    def is_authenticated(self) -> bool:
        """Check if authenticated."""
        if self.access_token:
            return True
        token_data = get_oauth_token("outlook")
        return token_data is not None

    def fetch_files(self) -> List[Dict]:
        """Not used - Outlook sync uses custom sync method."""
        return []

    def download_file(self, file_info: Dict) -> Optional[Path]:
        """Not used - Outlook sync uses custom sync method."""
        return None

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Dict = None
    ) -> Optional[Dict]:
        """Make authenticated request to Graph API."""
        if not self.access_token:
            if not self.authenticate():
                return None

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        url = f"{GRAPH_BASE}{endpoint}"

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params)
            else:
                response = requests.request(method, url, headers=headers, json=params)

            if response.status_code == 401:
                # Token expired, try refresh
                if self._refresh_tokens():
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    response = requests.get(url, headers=headers, params=params)

            if response.status_code == 200:
                return response.json()

            self.logger.warning(f"Graph API error: {response.status_code}")
            return None

        except Exception as e:
            self.logger.error(f"Request error: {e}")
            return None

    def _fetch_emails(
        self,
        folder: str = "inbox",
        top: int = 100,
        after_date: datetime = None
    ) -> Generator[Dict[str, Any], None, None]:
        """Fetch emails from Outlook."""
        params = {
            "$top": top,
            "$select": "id,subject,from,toRecipients,receivedDateTime,body,hasAttachments",
            "$orderby": "receivedDateTime DESC"
        }

        if after_date:
            params["$filter"] = f"receivedDateTime ge {after_date.isoformat()}"

        skip = 0
        while True:
            params["$skip"] = skip
            result = self._make_request(f"/me/mailFolders/{folder}/messages", params=params)

            if not result or "value" not in result:
                break

            for message in result["value"]:
                from_addr = message.get("from", {}).get("emailAddress", {})
                to_addrs = message.get("toRecipients", [])

                yield {
                    "id": message["id"],
                    "subject": message.get("subject", "(No Subject)"),
                    "from": from_addr.get("address", ""),
                    "from_name": from_addr.get("name", ""),
                    "to": ", ".join(r.get("emailAddress", {}).get("address", "") for r in to_addrs),
                    "date": message.get("receivedDateTime", ""),
                    "body": message.get("body", {}).get("content", ""),
                    "body_type": message.get("body", {}).get("contentType", "text"),
                    "has_attachments": message.get("hasAttachments", False)
                }

            if len(result["value"]) < top:
                break

            skip += top

    def _fetch_attachments(self, message_id: str) -> List[Dict[str, Any]]:
        """Fetch attachments for a message."""
        result = self._make_request(f"/me/messages/{message_id}/attachments")

        if not result or "value" not in result:
            return []

        attachments = []
        for att in result["value"]:
            if att.get("@odata.type") == "#microsoft.graph.fileAttachment":
                attachments.append({
                    "id": att["id"],
                    "name": att.get("name", "attachment"),
                    "content_type": att.get("contentType", ""),
                    "size": att.get("size", 0),
                    "content_bytes": att.get("contentBytes")  # Base64 encoded
                })

        return attachments

    def sync(
        self,
        search_engine=None,
        max_files: int = 500,
        days_back: int = 90
    ) -> Dict[str, int]:
        """Sync Outlook attachments to search index (attachments only, not email content)."""
        from semantic_search.search_engine import get_search_engine
        from semantic_search.file_processor import extract_text

        if search_engine is None:
            search_engine = get_search_engine()

        # If search engine is still None (cloud not configured), track files but don't index
        if search_engine is None:
            self.logger.warning("Search engine not available - tracking files only, not indexing")

        if not self.is_authenticated():
            if not self.authenticate():
                raise RuntimeError("Outlook not authenticated")

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

        # Only process emails that have attachments
        for email_data in self._fetch_emails(after_date=after_date, top=50):
            emails_checked += 1

            # Stop if we've indexed enough attachments
            if stats["indexed"] >= max_files:
                break

            # Skip emails without attachments
            if not email_data.get('has_attachments'):
                continue

            try:
                # Only process attachments, skip email content
                attachments = self._fetch_attachments(email_data['id'])

                for att in attachments:
                    if stats["indexed"] >= max_files:
                        break

                    stats["total"] += 1

                    try:
                        att_id = hashlib.sha256(f"outlook_att:{att['id']}".encode()).hexdigest()

                        if att_id in indexed_hashes:
                            stats["skipped"] += 1
                            continue

                        if att.get('content_bytes'):
                            safe_name = "".join(c for c in att['name'] if c.isalnum() or c in '.-_')
                            att_path = self.attachment_dir / f"{email_data['id']}_{safe_name}"

                            with open(att_path, 'wb') as f:
                                f.write(base64.b64decode(att['content_bytes']))

                            att_content = extract_text(str(att_path))

                            if att_content and len(att_content) > 20:
                                # Get the account email for opening the correct account
                                account_email = self.user_email or ''
                                if not account_email:
                                    token_data = get_oauth_token('outlook')
                                    if token_data:
                                        account_email = token_data.get('user_email', '')

                                att_metadata = {
                                    "filename": att['name'],
                                    "source": self.source_name,
                                    "file_path": str(att_path),
                                    "type": "attachment",
                                    "parent_email": email_data['subject'][:100] if email_data['subject'] else "(No Subject)",
                                    "from": email_data['from'],
                                    "date": email_data['date'],
                                    "outlook_message_id": email_data['id'],
                                    "account_email": account_email
                                }

                                batch.append({
                                    "id": att_id,
                                    "content": att_content,
                                    "metadata": att_metadata
                                })

                                upsert_file(
                                    filename=att['name'],
                                    file_path=str(att_path),
                                    source=self.source_name,
                                    file_hash=att_id,
                                    pinecone_id=att_id,
                                    metadata=json.dumps(att_metadata)
                                )

                                stats["indexed"] += 1

                    except Exception as e:
                        self.logger.warning(f"Error processing attachment {att.get('name', 'unknown')}: {e}")
                        stats["errors"] += 1

                if len(batch) >= batch_size and search_engine:
                    search_engine.index_batch(batch)
                    batch = []
                    self.logger.info(f"Indexed {stats['indexed']} Outlook attachments...")

            except Exception as e:
                self.logger.error(f"Error processing email attachments: {e}")
                stats["errors"] += 1

        # Index remaining batch
        if batch and search_engine:
            search_engine.index_batch(batch)

        self.logger.info(f"Outlook sync complete: checked {emails_checked} emails, {stats}")
        return stats
