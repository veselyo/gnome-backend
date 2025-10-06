const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const net = require('net');
const fs = require('fs');

// Load environment variables
// In development: use .env in electron folder
// In production: use .gnome-env in user's home directory
const isDev = !app.isPackaged;
if (isDev) {
  require('dotenv').config();
} else {
  const homedir = require('os').homedir();
  const envPath = path.join(homedir, '.gnome-env');
  if (fs.existsSync(envPath)) {
    require('dotenv').config({ path: envPath });
  }
}

let flaskProcess = null;
let mainWindow = null;
const FLASK_PORT = 5001;

// Check if Flask server is already running
function checkFlaskServer(callback) {
  const client = net.connect({ port: FLASK_PORT }, () => {
    client.end();
    callback(true);
  });

  client.on('error', () => {
    callback(false);
  });
}

// Start Flask backend
function startFlask() {
  return new Promise((resolve, reject) => {
    // Determine if we're in development or production
    const isDev = !app.isPackaged;

    // Path to Python backend
    let pythonPath, appPath;
    if (isDev) {
      // Development: use venv
      pythonPath = path.join(__dirname, '../venv/bin/python3');
      appPath = path.join(__dirname, '../demo/app.py');
    } else {
      // Production: use system Python (user must have Python 3.9+ installed)
      pythonPath = '/usr/bin/python3';
      appPath = path.join(process.resourcesPath, 'app', 'demo/app.py');
    }

    // Set environment variables (pass all to Flask)
    const env = Object.assign({}, process.env, {
      VOYAGE_API_KEY: process.env.VOYAGE_API_KEY || '',
      PINECONE_API_KEY: process.env.PINECONE_API_KEY || '',
      PINECONE_HOST: process.env.PINECONE_HOST || '',
      GOOGLE_CLIENT_ID: process.env.GOOGLE_CLIENT_ID || '',
      GOOGLE_CLIENT_SECRET: process.env.GOOGLE_CLIENT_SECRET || '',
      MICROSOFT_CLIENT_ID: process.env.MICROSOFT_CLIENT_ID || '',
      MICROSOFT_CLIENT_SECRET: process.env.MICROSOFT_CLIENT_SECRET || ''
    });

    console.log('Starting Flask server...');
    flaskProcess = spawn(pythonPath, [appPath], { env });

    let flaskReady = false;

    flaskProcess.stdout.on('data', (data) => {
      const output = data.toString();
      console.log(`Flask: ${output}`);
      // Check if Flask says it's running
      if (output.includes('Running on')) {
        flaskReady = true;
      }
    });

    flaskProcess.stderr.on('data', (data) => {
      const output = data.toString();
      console.error(`Flask Error: ${output}`);
      // Also check stderr for "Running on" message
      if (output.includes('Running on')) {
        flaskReady = true;
      }
    });

    flaskProcess.on('close', (code) => {
      console.log(`Flask process exited with code ${code}`);
      if (!flaskReady) {
        reject(new Error('Flask exited before starting'));
      }
    });

    // Wait 5 seconds for Flask to start
    setTimeout(() => {
      if (flaskReady) {
        console.log('Flask server is ready!');
        resolve();
      } else {
        reject(new Error('Flask server failed to start in time'));
      }
    }, 5000);
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

