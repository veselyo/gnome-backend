const { app, BrowserWindow, shell, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const net = require('net');
const fs = require('fs');

// Load environment variables
// In development: use .env in electron folder
// In production: use .gnome-env in user's home directory
const isDev = !app.isPackaged;
if (isDev) {
  // Explicitly load from electron/.env (where this file lives)
  const devEnvPath = path.join(__dirname, '.env');
  if (fs.existsSync(devEnvPath)) {
    require('dotenv').config({ path: devEnvPath });
    console.log('Loaded .env from:', devEnvPath);
  } else {
    console.warn('No .env file found at:', devEnvPath);
    require('dotenv').config();  // Fallback
  }
} else {
  const homedir = require('os').homedir();
  const envPath = path.join(homedir, '.gnome-env');
  if (fs.existsSync(envPath)) {
    require('dotenv').config({ path: envPath });
    console.log('Loaded .env from:', envPath);
  }
}

let flaskProcess = null;
let mainWindow = null;
const FLASK_PORT = 5001;

// Check if Flask server is ready using TCP connection
function checkFlaskServer() {
  return new Promise((resolve) => {
    const client = net.connect({ port: FLASK_PORT }, () => {
      client.end();
      resolve(true);
    });
    client.on('error', () => {
      resolve(false);
    });
    client.setTimeout(1000, () => {
      client.destroy();
      resolve(false);
    });
  });
}

// Wait for Flask to be ready with polling
async function waitForFlask(maxAttempts = 30, intervalMs = 1000) {
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const isReady = await checkFlaskServer();
    if (isReady) {
      console.log(`Flask server ready after ${attempt} attempt(s)`);
      return true;
    }
    console.log(`Waiting for Flask... (attempt ${attempt}/${maxAttempts})`);
    await new Promise(r => setTimeout(r, intervalMs));
  }
  return false;
}

// Start Flask backend
function startFlask() {
  return new Promise(async (resolve, reject) => {
    // Check if Flask is already running
    const alreadyRunning = await checkFlaskServer();
    if (alreadyRunning) {
      console.log('Flask server already running on port ' + FLASK_PORT);
      resolve();
      return;
    }

    // Determine if we're in development or production
    const isDev = !app.isPackaged;

    // Path to Python backend
    let backendPath, projectRoot;
    let spawnArgs;

    if (isDev) {
      // Development: use venv Python with app.py
      projectRoot = path.join(__dirname, '..');
      const pythonPath = path.join(projectRoot, 'venv/bin/python3');
      const appPath = path.join(projectRoot, 'demo/app.py');
      backendPath = pythonPath;
      spawnArgs = [appPath];
      console.log('Development mode - using venv Python');
    } else {
      // Production: use PyInstaller-bundled executable
      projectRoot = path.join(process.resourcesPath, 'app');
      backendPath = path.join(projectRoot, 'backend', 'gnome-backend', 'gnome-backend');

      // Check if bundled backend exists
      if (!fs.existsSync(backendPath)) {
        // Fallback to system Python if bundled backend not found
        console.warn('Bundled backend not found, falling back to system Python');
        backendPath = '/usr/bin/python3';
        spawnArgs = [path.join(projectRoot, 'demo/app.py')];
      } else {
        spawnArgs = [];
        console.log('Production mode - using bundled Python backend');
      }
    }

    // ============ PRODUCTION CONFIG (Baked In) ============
    // These are safe public identifiers - all secrets stay on the proxy server
    const PROXY_URL = 'https://gnome-production.up.railway.app';
    const GOOGLE_CLIENT_ID = '200229085583-tasbpc46mnl4ahs2hj3ouqtmjf1jdnv5.apps.googleusercontent.com';
    const MICROSOFT_CLIENT_ID = '9ff39189-1c55-4b23-8cb2-fdeebffe1d70';

    // Set environment variables (pass all to Flask)
    const env = Object.assign({}, process.env, {
      PYTHONPATH: projectRoot,
      // Proxy server URL (handles embeddings, search, and OAuth)
      PROXY_URL: process.env.PROXY_URL || PROXY_URL,
      // OAuth Client IDs (public identifiers - safe to bake in)
      GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID || GOOGLE_CLIENT_ID,
      MICROSOFT_CLIENT_ID: process.env.MICROSOFT_CLIENT_ID || MICROSOFT_CLIENT_ID,
      // Local API keys (optional - if set, app uses direct mode instead of proxy)
      VOYAGE_API_KEY: process.env.VOYAGE_API_KEY || '',
      PINECONE_API_KEY: process.env.PINECONE_API_KEY || '',
      PINECONE_HOST: process.env.PINECONE_HOST || ''
    });

    console.log('Starting Flask server...');
    console.log('Backend path:', backendPath);
    console.log('Spawn args:', spawnArgs);
    console.log('Project root:', projectRoot);

    flaskProcess = spawn(backendPath, spawnArgs, {
      env,
      cwd: projectRoot
    });

    flaskProcess.stdout.on('data', (data) => {
      console.log(`Flask: ${data.toString()}`);
    });

    flaskProcess.stderr.on('data', (data) => {
      console.error(`Flask: ${data.toString()}`);
    });

    flaskProcess.on('close', (code) => {
      console.log(`Flask process exited with code ${code}`);
    });

    flaskProcess.on('error', (err) => {
      console.error('Failed to start Flask:', err);
      reject(new Error(`Failed to start Flask: ${err.message}`));
    });

    // Wait for Flask to be ready using TCP polling
    const isReady = await waitForFlask(30, 1000);
    if (isReady) {
      console.log('Flask server is ready!');
      resolve();
    } else {
      reject(new Error('Flask server failed to start after 30 seconds'));
    }
  });
}

// Create the main window
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    title: 'Gnome',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    icon: path.join(__dirname, 'icon.png')
  });

  // Load the Flask app
  mainWindow.loadURL(`http://localhost:${FLASK_PORT}`);

  // Open DevTools in development
  if (process.env.NODE_ENV === 'development') {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// App lifecycle
app.on('ready', async () => {
  try {
    await startFlask();
    createWindow();
  } catch (error) {
    console.error('Failed to start application:', error);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});

app.on('quit', () => {
  if (flaskProcess) {
    flaskProcess.kill('SIGTERM');
  }
});

// Handle graceful shutdown
process.on('SIGTERM', () => {
  if (flaskProcess) {
    flaskProcess.kill('SIGTERM');
  }
  app.quit();
});

// IPC handler to open local files - avoids macOS sandbox permission issues
ipcMain.handle('open-file', async (event, filePath) => {
  try {
    const result = await shell.openPath(filePath);
    if (result) {
      // shell.openPath returns error string if failed, empty string if success
      console.error('Failed to open file:', result);
      return { success: false, error: result };
    }
    console.log('Opened file:', filePath);
    return { success: true };
  } catch (error) {
    console.error('Error opening file:', error);
    return { success: false, error: error.message };
  }
});

