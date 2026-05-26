const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  selectExportDirectory: () => ipcRenderer.invoke("select-export-directory"),
});
