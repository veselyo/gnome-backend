#!/usr/bin/env python3
"""
Test OAuth connections for Google Drive and OneDrive.
Run this before deploying to verify credentials work.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from database.models import GnomeDatabase
from sync_engine.gdrive_sync import GoogleDriveSyncEngine
from sync_engine.onedrive_sync import OneDriveSyncEngine
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_google_drive():
    """Test Google Drive OAuth connection."""
    print("\n" + "="*60)
    print("TESTING GOOGLE DRIVE CONNECTION")
    print("="*60)
    
    # Check credentials
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        print("❌ Google Drive OAuth not configured!")
        print("   Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
        print("   See OAUTH-QUICK-SETUP.md for instructions")
        return False
    
    print(f"✅ Client ID found: {client_id[:20]}...")
    print(f"✅ Client Secret found: {client_secret[:10]}...")
    
    # Initialize
    db = GnomeDatabase()
    engine = GoogleDriveSyncEngine(db)
    
    # Try to authenticate
    print("\n🔐 Starting authentication...")
    print("   (Browser will open for Google login)")
    
    try:
        success = engine.authenticate()
        
        if success:
            print("\n✅ GOOGLE DRIVE CONNECTED!")
            
            # Try to fetch files
            print("\n📁 Fetching files...")
            files = engine.fetch_files()
            print(f"✅ Found {len(files)} PDF files in Google Drive")
            
            if files:
                print("\n📄 Sample files:")
                for file in files[:5]:
                    print(f"   - {file['filename']}")
            
            db.close()
            return True
        else:
            print("\n❌ Authentication failed")
            db.close()
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.close()
        return False


def test_onedrive():
    """Test OneDrive OAuth connection."""
    print("\n" + "="*60)
    print("TESTING ONEDRIVE CONNECTION")
    print("="*60)
    
    # Check credentials
    client_id = os.environ.get('MICROSOFT_CLIENT_ID')
    client_secret = os.environ.get('MICROSOFT_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        print("❌ OneDrive OAuth not configured!")
        print("   Please set MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET")
        print("   See OAUTH-QUICK-SETUP.md for instructions")
        return False
    
    print(f"✅ Client ID found: {client_id[:20]}...")
    print(f"✅ Client Secret found: {client_secret[:10]}...")
    
    # Initialize
    db = GnomeDatabase()
    engine = OneDriveSyncEngine(db)
    
    # Try to authenticate
    print("\n🔐 Starting authentication...")
    print("   (Device code will be displayed - follow instructions)")
    
    try:
        success = engine.authenticate()
        
        if success:
            print("\n✅ ONEDRIVE CONNECTED!")
            
            # Try to fetch files
            print("\n📁 Fetching files...")
            files = engine.fetch_files()
            print(f"✅ Found {len(files)} PDF files in OneDrive")
            
            if files:
                print("\n📄 Sample files:")
                for file in files[:5]:
                    print(f"   - {file['filename']}")
            
            db.close()
            return True
        else:
            print("\n❌ Authentication failed")
            db.close()
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.close()
        return False


if __name__ == "__main__":
    print("\n🏡 GNOME OAUTH TEST SUITE")
    print("="*60)
    
    # Test Google Drive
    gdrive_ok = test_google_drive()
    
    # Test OneDrive
    onedrive_ok = test_onedrive()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Google Drive: {'✅ READY' if gdrive_ok else '❌ NOT CONFIGURED'}")
    print(f"OneDrive:     {'✅ READY' if onedrive_ok else '❌ NOT CONFIGURED'}")
    print("="*60)
    
    if gdrive_ok or onedrive_ok:
        print("\n✅ At least one cloud service is configured!")
        print("   Restart Gnome to use these connections.")
    else:
        print("\n⚠️  No cloud services configured")
        print("   You can still use Finder (local files)")
        print("   See OAUTH-QUICK-SETUP.md to add cloud storage")
    
    print("\n")

