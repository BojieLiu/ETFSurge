"""Start backend with PROFILE_WARMUP=1 for performance profiling."""
import os
import sys
import uvicorn

os.environ["PROFILE_WARMUP"] = "1"
backend_dir = os.path.join(os.path.dirname(__file__), "backend")
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )
