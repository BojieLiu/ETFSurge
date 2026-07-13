"""启动后端服务器并等待就绪。"""
import os, sys, time, subprocess, socket, signal

PORT = 8000
LOG_FILE = os.path.join(os.path.dirname(__file__), "uvicorn.log")

def kill_port(port):
    """Kill any process listening on the given port."""
    try:
        import psutil
        for conn in psutil.net_connections():
            if conn.laddr.port == port and conn.status == "LISTEN":
                proc = psutil.Process(conn.pid)
                proc.kill()
                print(f"  Killed PID {conn.pid} on port {port}")
                time.sleep(1)
                return True
    except ImportError:
        pass
    # Fallback: use netstat + taskkill
    result = os.popen(f'netstat -ano | findstr LISTEN | findstr :{port}').read().strip()
    if result:
        parts = result.split()
        pid = parts[-1] if parts else ""
        if pid.isdigit():
            os.system(f"taskkill /F /PID {pid} >nul 2>&1")
            print(f"  Killed PID {pid} on port {port}")
            time.sleep(1)
            return True
    return False

def is_port_open(port):
    """Check if a process is listening on the port."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(('127.0.0.1', port))
        s.close()
        return result == 0
    except:
        return False

def wait_for_server(port, timeout=15):
    """Wait for the server to start responding."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            import httpx
            r = httpx.get(f'http://127.0.0.1:{port}/api/v1/market/realtime', timeout=2)
            if r.status_code == 200:
                elapsed = time.time() - start
                print(f"  Server ready in {elapsed:.1f}s")
                return True
        except:
            pass
        time.sleep(0.5)
    return False

def main():
    print(f"Starting server on port {PORT}...")
    
    # Kill existing process
    if is_port_open(PORT):
        print(f"  Port {PORT} is in use, killing...")
        kill_port(PORT)
    
    # Remove old log
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    
    # Start server
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
        cwd=os.path.dirname(__file__),
        stdout=open(LOG_FILE, "w"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    print(f"  Started PID {proc.pid}")
    
    # Wait for ready
    if wait_for_server(PORT):
        print("  Server is ready!")
        return 0
    else:
        print("  ERROR: Server failed to start within timeout")
        # Print last lines of log
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                lines = f.readlines()
                for line in lines[-10:]:
                    print(f"    {line.strip()}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
