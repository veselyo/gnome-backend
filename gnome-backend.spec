# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Gnome Backend
Bundles the Flask app with all Python dependencies for macOS.
"""

import os
import sys
from pathlib import Path

block_cipher = None

# Get the project root directory
project_root = os.path.dirname(os.path.abspath(SPEC))

# Collect data files (templates, static files)
datas = [
    (os.path.join(project_root, 'demo', 'templates'), 'demo/templates'),
    (os.path.join(project_root, 'demo', 'static'), 'demo/static'),
]

# Hidden imports that PyInstaller might miss
hiddenimports = [
    # Flask and web
    'flask',
    'flask.json',
    'flask.templating',
    'jinja2',
    'werkzeug',
    'markupsafe',

    # Voyage AI
    'voyageai',
    'voyageai.client',

    # Pinecone
    'pinecone',
    'pinecone.grpc',

    # Google APIs
    'google.auth',
    'google.auth.transport.requests',
    'google.oauth2.credentials',
    'google_auth_oauthlib.flow',
    'googleapiclient.discovery',
    'googleapiclient.http',

    # Microsoft/MSAL
    'msal',
    'msal.application',

    # Document processing
    'fitz',  # PyMuPDF
    'PIL',
    'PIL.Image',
    'docx',
    'pptx',
    'openpyxl',

    # BM25
    'rank_bm25',

    # Utilities
    'dotenv',
    'watchdog',
    'watchdog.observers',
    'watchdog.events',
    'numpy',
    'requests',

    # Standard library modules that might be missed
    'sqlite3',
    'json',
    'hashlib',
    'uuid',
    'threading',
    'logging',
    'email',
    'email.mime',
    'email.mime.text',
    'email.mime.multipart',
    'smtplib',
    'socket',
    'subprocess',
    'webbrowser',
    're',
    'base64',
    'tempfile',
    'time',
    'datetime',
    'pathlib',
    'typing',
    'traceback',
    'secrets',
    'platform',
]

a = Analysis(
    [os.path.join(project_root, 'demo', 'app.py')],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary packages to reduce size
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'pytest',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='gnome-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keep console for debugging; change to False for production
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',  # Apple Silicon
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='gnome-backend',
)
