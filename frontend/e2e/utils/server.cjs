// E2E server lifecycle management — CommonJS version for Playwright compatibility
// Windows-compatible: uses cmd.exe /c for uvicorn / npx, net module for port polling.
const { spawn } = require('child_process')
const net = require('net')
const path = require('path')

const BACKEND_DIR = path.resolve(__dirname, '../../backend')
const FRONTEND_DIR = path.resolve(__dirname, '../..')
const BACKEND_PORT = 8000
const FRONTEND_PORT = 5173

// --------------- helpers ---------------

/**
 * Poll a TCP port until it is open or the timeout expires.
 * @param {number} port
 * @param {string} host
 * @param {number} timeoutMs
 * @returns {Promise<void>}
 */
function waitForPort(port, host = '127.0.0.1', timeoutMs = 30000) {
  const start = Date.now()
  return new Promise((resolve, reject) => {
    function tryConnect() {
      const sock = new net.Socket()
      sock.setTimeout(1000)
      sock.on('connect', () => { sock.destroy(); resolve() })
      sock.on('error', () => sock.destroy())
      sock.on('timeout', () => sock.destroy())
      sock.connect(port, host)
      if (Date.now() - start >= timeoutMs) {
        reject(new Error(`Port ${port} not ready within ${timeoutMs}ms`))
      } else {
        setTimeout(tryConnect, 500)
      }
    }
    tryConnect()
  })
}

let backend = null
let frontend = null

async function startServers() {
  // Start backend — pass env with UTF-8 encoding
  backend = spawn('uvicorn', ['app.main:app', '--port', String(BACKEND_PORT)], {
    cwd: BACKEND_DIR,
    stdio: 'pipe',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
  backend.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  await waitForPort(BACKEND_PORT, '127.0.0.1', 120000)

  // Start frontend Vite — use node_modules/.bin/vite directly to avoid cmd.exe dependency
  frontend = spawn('node', [require.resolve('vite/bin/vite.js'), '--port', String(FRONTEND_PORT)], {
    cwd: FRONTEND_DIR,
    stdio: 'pipe',
  })
  frontend.stderr.on('data', (d) => process.stderr.write(`[frontend] ${d}`))
  await waitForPort(FRONTEND_PORT, '127.0.0.1', 60000)
}

async function stopServers() {
  if (backend) { backend.kill('SIGTERM'); backend = null }
  if (frontend) { frontend.kill('SIGTERM'); frontend = null }
  await new Promise(r => setTimeout(r, 1000))
}

module.exports = { startServers, stopServers }
