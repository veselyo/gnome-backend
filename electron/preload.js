// Preload script for security
const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electron', {
  platform: process.platform,
  version: process.versions.electron,
  // Open local file using native shell (avoids sandbox permission issues)
  openFile: (filePath) => ipcRenderer.invoke('open-file', filePath)
});

