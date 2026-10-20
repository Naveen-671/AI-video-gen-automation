"""Script to start the FastAPI server serving both API and static frontend."""

import uvicorn
from backend.app.config import FRONTEND_OUT_DIR

if __name__ == "__main__":
    print(f"Starting server on http://127.0.0.1:8000")
    print(f"Static frontend directory: {FRONTEND_OUT_DIR} (exists: {FRONTEND_OUT_DIR.exists()})")
    uvicorn.run("backend.app.api.main:app", host="127.0.0.1", port=8000, log_level="info")
