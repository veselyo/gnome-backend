"""
OneDrive sync engine using Microsoft Graph API and MSAL OAuth.
"""
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import tempfile
import os
import time
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
            CLIENT_ID = os.environ.get('MICROSOFT_CLIENT_ID')
            CLIENT_SECRET = os.environ.get('MICROSOFT_CLIENT_SECRET')
            
            if not CLIENT_ID or not CLIENT_SECRET:
                self.logger.warning("Microsoft OAuth not configured (MICROSOFT_CLIENT_ID/SECRET missing)")
                return False
                
            import msal
            
            AUTHORITY = 'https://login.microsoftonline.com/common'
            SCOPES = ['Files.Read.All', 'offline_access']
            
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
                self.logger.info("✅ OneDrive authentication successful")
                
                # Test the connection
                try:
                    headers = {'Authorization': f'Bearer {self.access_token}'}
                    test_response = requests.get(f"{self.graph_endpoint}/me", headers=headers)
                    if test_response.status_code == 200:
                        user_data = test_response.json()
                        user_name = user_data.get('displayName', 'Unknown')
                        self.logger.info(f"✅ Connected to OneDrive as: {user_name}")
                    else:
                        self.logger.warning("Auth succeeded but connection test failed")
                except Exception as test_error:
                    self.logger.warning(f"Auth succeeded but test failed: {test_error}")
                
                return True
            else:
                self.logger.error(f"❌ Authentication failed: {result.get('error_description')}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ OneDrive authentication failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    def is_authenticated(self) -> bool:
        """Check if OneDrive is authenticated."""
        # Check if we have tokens
        token_data = self.db.get_oauth_token('onedrive')
        return token_data is not None or self.access_token is not None
    
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
        Fetch PDF files from OneDrive with retry logic and better error handling.
        
        Returns:
            List of file info dicts
        """
        if not self.access_token:
            if not self.authenticate():
                self.logger.error("Cannot fetch files - not authenticated")
                return []
        
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
                            if self.authenticate():
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
                                    'download_url': item.get('webUrl'),
                                    'metadata': {
                                        'onedrive_id': item['id'],
                                        'download_link': item.get('@microsoft.graph.downloadUrl'),
                                        'webUrl': item.get('webUrl')  # URL to open in browser
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
            
            self.logger.info(f"✅ Fetched {len(files)} PDFs from OneDrive")
            return files
            
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch OneDrive files: {e}")
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
            temp_file = temp_dir / file_info['filename']
            
            with open(temp_file, 'wb') as f:
                f.write(content)
            
            self.logger.info(f"Downloaded: {file_info['filename']}")
            return temp_file
            
        except Exception as e:
            self.logger.error(f"Failed to download {file_info['filename']}: {e}")
            return None

