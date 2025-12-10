import { app, BrowserWindow, screen, ipcMain } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';

// 获取 __dirname 等效变量 (ES Module 兼容)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const isDev = !app.isPackaged;

function createPetWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  const win = new BrowserWindow({
    width: 400,
    height: 400,
    x: width - 420,
    y: height - 450,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      webSecurity: false
    },
    resizable: false,
    hasShadow: false
  });

  const startUrl = isDev 
    ? 'http://127.0.0.1:3001/#/pet-mode' 
    : `file://${path.join(__dirname, '../dist/index.html')}#/pet-mode`;

  // Make window click-through by default (except when hovered, handled by renderer)
  // Initially interactive so we can grab it? No, let renderer decide.
  // Actually, we usually want it interactive by default for the "Pet" area.
  // The renderer will send 'set-ignore-mouse-events' true/false.

  // 在开发模式下，等待加载，如果失败则重试
  const loadWithRetry = (url, retries = 10) => {
    win.loadURL(url).catch(err => {
      if (retries > 0) {
        setTimeout(() => loadWithRetry(url, retries - 1), 2000);
      } else {
        console.error('Failed to load URL:', url, err);
      }
    });
  };

  loadWithRetry(startUrl);

  // 打开开发者工具 (可选，调试用)
  // win.webContents.openDevTools({ mode: 'detach' });
}

app.whenReady().then(() => {
  createPetWindow();

  // IPC 监听：控制鼠标穿透
  ipcMain.on('set-ignore-mouse-events', (event, ignore, options) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win) {
      win.setIgnoreMouseEvents(ignore, options);
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
