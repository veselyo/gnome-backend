"""
OneDrive sync engine using Microsoft Graph API and MSAL OAuth.
"""
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import tempfile
import os
import requests
from sync_engine.base_sync import BaseSyncEngine


class OneDriveSyncEngine(BaseSyncEngine):
    """Sync engine for OneDrive files."""
    
    def __init__(self, database):
        super().__init__(database, 'OneDrive')
        self.access_token = None
        self.graph_endpoint = 'https://graph.microsoft.com/v1.0'
    
    def authenticate(self) -> bool:
        """
        Authenticate with OneDrive using MSAL (Microsoft Authentication Library).
        
        Returns:
            True if authentication successful
        """
        try:
            import msal
            import os
            
            CLIENT_ID = os.environ.get('MICROSOFT_CLIENT_ID')
            CLIENT_SECRET = os.environ.get('MICROSOFT_CLIENT_SECRET')
            AUTHORITY = 'https://login.microsoftonline.com/common'
            SCOPES = ['Files.Read.All', 'offline_access']
            
            if not CLIENT_ID or not CLIENT_SECRET:
                self.logger.error("Microsoft OAuth credentials not configured")
                return False
            
            # Check if we have stored tokens
            token_data = self.db.get_oauth_token('onedrive')
            
            app = msal.ConfidentialClientApplication(
                CLIENT_ID,
                authority=AUTHORITY,
                client_credential=CLIENT_SECRET
            )
            
            if token_data and token_data.get('refresh_token'):
                # Try to refresh the token
                result = app.acquire_token_by_refresh_token(
                    token_data['refresh_token'],
                    scopes=SCOPES
                )
                
                if 'access_token' in result:
                    self.access_token = result['access_token']
                    self.save_tokens(result)
                    self.logger.info("OneDrive token refreshed")
                    return True
            
            # No valid token - need to authenticate
            flow = app.initiate_device_flow(scopes=SCOPES)
            
            if 'user_code' not in flow:
                raise ValueError("Failed to create device flow")
            
            print("\n" + "="*50)
            print("OneDrive Authentication Required")
            print("="*50)
            print(flow['message'])
            print("="*50 + "\n")
            
            # Wait for user to authenticate
            result = app.acquire_token_by_device_flow(flow)
            
            if 'access_token' in result:
                self.access_token = result['access_token']
                self.save_tokens(result)
                self.logger.info("OneDrive authentication successful")
                return True
            else:
                self.logger.error(f"Authentication failed: {result.get('error_description')}")
                return False
                
        except Exception as e:
            self.logger.error(f"OneDrive authentication failed: {e}")
            return False
    
    def save_tokens(self, token_response: Dict):
        """Save OAuth tokens to database."""
        expires_at = None
        if 'expires_in' in token_response:
            from datetime import timedelta
            expires_at = (datetime.now() + timedelta(seconds=token_response['expires_in'])).isoformat()
        
        self.db.save_oauth_token(
            'onedrive',
            token_response['access_token'],
            token_response.get('refresh_token'),
            expires_at
        )
    
    def fetch_files(self) -> List[Dict]:
        """
        Fetch PDF files from OneDrive.
        
        Returns:
            List of file info dicts
        """
        if not self.access_token:
            if not self.authenticate():
                return []
        
        files = []
        next_link = f"{self.graph_endpoint}/me/drive/root/search(q='.pdf')"
        
        try:
            while next_link:
                headers = {'Authorization': f'Bearer {self.access_token}'}
                response = requests.get(next_link, headers=headers)
                
                if response.status_code == 401:
                    # Token expired, re-authenticate
                    if self.authenticate():
                        headers = {'Authorization': f'Bearer {self.access_token}'}
                        response = requests.get(next_link, headers=headers)
                    else:
                        break
                
                if response.status_code != 200:
                    self.logger.error(f"OneDrive API error: {response.status_code}")
                    break
                
                data = response.json()
                
                for item in data.get('value', []):
                    # Only process PDF files
                    if item.get('file') and item['name'].lower().endswith('.pdf'):
                        files.append({
                            'filename': item['name'],
                            'file_path': item['id'],  # Use OneDrive ID
                            'file_size': item.get('size', 0),
                            'last_modified': datetime.fromisoformat(item['lastModifiedDateTime'].replace('Z', '+00:00')),
                            'file_hash': item['id'],  # Use ID as hash
                            'download_url': item.get('webUrl'),
                            'metadata': {
                                'onedrive_id': item['id'],
                                'download_link': item.get('@microsoft.graph.downloadUrl')
                            }
                        })
                
                next_link = data.get('@odata.nextLink')
            
            self.logger.info(f"Fetched {len(files)} PDFs from OneDrive")
            return files
            
        except Exception as e:
            self.logger.error(f"Failed to fetch OneDrive files: {e}")
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
            temp_file = temp_dir / file_info['filename']
            
            with open(temp_file, 'wb') as f:
                f.write(content)
            
            self.logger.info(f"Downloaded: {file_info['filename']}")
            return temp_file
            
        except Exception as e:
            self.logger.error(f"Failed to download {file_info['filename']}: {e}")
            return None

