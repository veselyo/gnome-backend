#!/usr/bin/env python3
"""
Backend health check - validates all systems are working.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import os
from dotenv import load_dotenv
from database.models import GnomeDatabase
from semantic_search.embedding_engine import init_voyage
from semantic_search.vector_database import init_pinecone_idx

load_dotenv()


def check_env_vars():
    """Check all required environment variables."""
    print("\n🔍 Checking Environment Variables...")
    print("-" * 60)
    
    required = {
        'VOYAGE_API_KEY': 'Voyage AI (embeddings)',
        'PINECONE_API_KEY': 'Pinecone (vector DB)',
        'PINECONE_HOST': 'Pinecone host URL'
    }
    
    optional = {
        'GOOGLE_CLIENT_ID': 'Google Drive sync',
        'GOOGLE_CLIENT_SECRET': 'Google Drive sync',
        'MICROSOFT_CLIENT_ID': 'OneDrive sync',
        'MICROSOFT_CLIENT_SECRET': 'OneDrive sync'
    }
    
    all_good = True
    
    # Check required
    for var, description in required.items():
        value = os.environ.get(var)
        if value:
            print(f"✅ {var:25} ({description})")
        else:
            print(f"❌ {var:25} MISSING! ({description})")
            all_good = False
    
    # Check optional
    print(f"\nOptional (for cloud sync):")
    for var, description in optional.items():
        value = os.environ.get(var)
        if value:
            print(f"✅ {var:25} ({description})")
        else:
            print(f"⚠️  {var:25} Not set ({description})")
    
    return all_good


def check_database():
    """Check database connection and tables."""
    print("\n🗄️  Checking Database...")
    print("-" * 60)
    
    try:
        db = GnomeDatabase()
        
        # Check tables exist
        cursor = db.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        expected_tables = ['files', 'sync_state', 'oauth_tokens', 'watched_folders']
        for table in expected_tables:
            if table in tables:
                # Count records
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"✅ Table '{table}': {count} records")
            else:
                print(f"❌ Table '{table}': MISSING!")
                return False
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False


def check_voyage_ai():
    """Check Voyage AI connection."""
    print("\n🤖 Checking Voyage AI...")
    print("-" * 60)
    
    try:
        client = init_voyage()
        
        # Try a simple embedding
        test_response = client.embed(
            texts=["test"],
            model="voyage-3",
            input_type="query"
        )
        
        if test_response and test_response.embeddings:
            print(f"✅ Voyage AI connected")
            print(f"   Embedding dimension: {len(test_response.embeddings[0])}")
            return True
        else:
            print("❌ Voyage AI returned empty response")
            return False
            
    except Exception as e:
        print(f"❌ Voyage AI error: {e}")
        return False


def check_pinecone():
    """Check Pinecone connection."""
    print("\n📊 Checking Pinecone...")
    print("-" * 60)
    
    try:
        idx = init_pinecone_idx()
        stats = idx.describe_index_stats()
        
        demo_stats = stats.get('namespaces', {}).get('demo', {})
        vector_count = demo_stats.get('vector_count', 0)
        
        print(f"✅ Pinecone connected")
        print(f"   Namespace 'demo': {vector_count} vectors")
        print(f"   Dimension: {stats.get('dimension', 'Unknown')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Pinecone error: {e}")
        return False


def check_sync_engines():
    """Check sync engine initialization."""
    print("\n🔄 Checking Sync Engines...")
    print("-" * 60)
    
    try:
        from sync_engine.finder_sync import FinderSyncEngine
        from sync_engine.gdrive_sync import GoogleDriveSyncEngine
        from sync_engine.onedrive_sync import OneDriveSyncEngine
        
        db = GnomeDatabase()
        
        # Finder
        print("✅ Finder sync engine loaded")
        finder = FinderSyncEngine(db)
        print(f"   Default folders: Documents, Downloads, Desktop")
        
        # Google Drive
        print("✅ Google Drive sync engine loaded")
        gdrive = GoogleDriveSyncEngine(db)
        is_authed = gdrive.is_authenticated()
        print(f"   Authenticated: {'Yes ✅' if is_authed else 'No (setup required)'}")
        
        # OneDrive
        print("✅ OneDrive sync engine loaded")
        onedrive = OneDriveSyncEngine(db)
        is_authed = onedrive.is_authenticated()
        print(f"   Authenticated: {'Yes ✅' if is_authed else 'No (setup required)'}")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Sync engine error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "="*60)
    print("🏡 GNOME BACKEND HEALTH CHECK")
    print("="*60)
    
    results = {
        'Environment Variables': check_env_vars(),
        'Database': check_database(),
        'Voyage AI': check_voyage_ai(),
        'Pinecone': check_pinecone(),
        'Sync Engines': check_sync_engines()
    }
    
    print("\n" + "="*60)
    print("HEALTH CHECK SUMMARY")
    print("="*60)
    
    all_pass = True
    for component, status in results.items():
        icon = "✅" if status else "❌"
        print(f"{icon} {component:25} {'PASS' if status else 'FAIL'}")
        if not status:
            all_pass = False
    
    print("="*60)
    
    if all_pass:
        print("\n🎉 ALL SYSTEMS GO!")
        print("   Gnome is ready to launch")
    else:
        print("\n⚠️  SOME COMPONENTS NOT READY")
        print("   Fix the failed checks above")
    
    print("\n")
    sys.exit(0 if all_pass else 1)

