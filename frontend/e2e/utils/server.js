// E2E server lifecycle management
// Windows-compatible: uses cmd.exe /c for uvicorn / npx, net module for port polling.
import { spawn } from 'child_process'
import * as net from 'net'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

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
      sock.on('connect', () => {
        sock.destroy()
        resolve()
      })
      sock.on('error', () => sock.destroy())
      sock.on('timeout', () => sock.destroy())

      if (Date.now() - start >= timeoutMs) {
        reject(new Error(`Port ${port} did not become ready within ${timeoutMs}ms`))
        return
      }
      sock.connect(port, host)
      setTimeout(tryConnect, 500)
    }
    tryConnect()
  })
}

// --------------- process refs ---------------

/** @type {import('child_process').ChildProcess | null} */
let backend = null
/** @type {import('child_process').ChildProcess | null} */
let frontend = null

// --------------- public API ---------------

/**
 * Start backend (uvicorn) and frontend (Vite dev server).
 * Both are spawned through cmd.exe /c for Windows .cmd resolution.
 */
export async function startServers() {
  // Start backend — uvicorn on port 8000
  backend = spawn(
    'cmd.exe',
    ['/c', 'uvicorn', 'app.main:app', '--port', String(BACKEND_PORT)],
    {
      cwd: BACKEND_DIR,
      shell: true,
      stdio: 'pipe',
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    }
  )
  backend.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`))
  await waitForPort(BACKEND_PORT, '127.0.0.1', 30000)

  // Start frontend — Vite dev server on port 5173
  frontend = spawn(
    'cmd.exe',
    ['/c', 'npx', 'vite', '--port', String(FRONTEND_PORT)],
    {
      cwd: FRONTEND_DIR,
      shell: true,
      stdio: 'pipe',
    }
  )
  frontend.stderr.on('data', (d) => process.stderr.write(`[frontend] ${d}`))
  await waitForPort(FRONTEND_PORT, '127.0.0.1', 30000)
}

/**
 * Stop both servers gracefully.
 */
export async function stopServers() {
  if (backend) {
    backend.kill('SIGTERM')
    backend = null
  }
  if (frontend) {
    frontend.kill('SIGTERM')
    frontend = null
  }
  // Allow processes to exit
  await new Promise((r) => setTimeout(r, 1000))
}
