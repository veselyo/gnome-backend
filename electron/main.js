require('dotenv').config();
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const net = require('net');

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
    // Check if already running
    checkFlaskServer((isRunning) => {
      if (isRunning) {
        console.log('Flask server already running');
        resolve();
        return;
      }

      // Path to Python backend (development mode)
      const pythonPath = path.join(__dirname, '../venv/bin/python3');
      const appPath = path.join(__dirname, '../demo/app.py');
      
      // Set environment variables
      const env = Object.assign({}, process.env, {
        VOYAGE_API_KEY: process.env.VOYAGE_API_KEY || '',
        PINECONE_API_KEY: process.env.PINECONE_API_KEY || '',
        PINECONE_HOST: process.env.PINECONE_HOST || ''
      });

      console.log('Starting Flask server...');
      flaskProcess = spawn(pythonPath, [appPath], { env });

      flaskProcess.stdout.on('data', (data) => {
        console.log(`Flask: ${data}`);
      });

      flaskProcess.stderr.on('data', (data) => {
        console.error(`Flask Error: ${data}`);
      });

      flaskProcess.on('close', (code) => {
        console.log(`Flask process exited with code ${code}`);
      });

      // Wait for Flask to be ready
      let attempts = 0;
      const checkInterval = setInterval(() => {
        checkFlaskServer((isRunning) => {
          if (isRunning) {
            clearInterval(checkInterval);
            console.log('Flask server is ready!');
            resolve();
          } else if (attempts++ > 30) {
            clearInterval(checkInterval);
            reject(new Error('Flask server failed to start'));
          }
        });
      }, 500);
    });
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

