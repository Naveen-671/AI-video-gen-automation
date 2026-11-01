from pathlib import Path
import os
import psutil

# Root project paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "factory.db"
MEDIA_DIR = DATA_DIR / "media"
INBOX_DIR = DATA_DIR / "inbox"
SECRETS_DIR = DATA_DIR / "secrets"
FRONTEND_OUT_DIR = BASE_DIR / "frontend" / "out"

# YouTube OAuth & Publishing Secrets
YOUTUBE_SECRETS_FILE = SECRETS_DIR / "youtube_credentials.json"
YOUTUBE_CLIENT_SECRET_FILE = SECRETS_DIR / "client_secret.json"
YOUTUBE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/youtube/callback")

# Hardware Resource Limits (from ADR-11)
MIN_FREE_RAM_GIB = 3.0
MIN_FREE_DISK_GB = 10.0
MAX_CONCURRENT_GPU_JOBS = 1
MEDIA_CACHE_CAP_GB = 15.0

# Supported Provider Cost Classes
ALLOWED_COST_CLASSES = {"free_local", "free_quota", "manual"}
DISALLOWED_DEFAULT_COST_CLASSES = {"metered"}

def check_system_resources() -> dict:
    """Check current host memory, swap, and disk headroom against ADR-11 guardrails."""
    mem = psutil.virtual_memory()
    available_ram_gib = mem.available / (1024 ** 3)
    
    disk = psutil.disk_usage(str(DATA_DIR if DATA_DIR.exists() else BASE_DIR))
    free_disk_gb = disk.free / (1024 ** 3)

    ram_ok = available_ram_gib >= MIN_FREE_RAM_GIB
    disk_ok = free_disk_gb >= MIN_FREE_DISK_GB

    return {
        "available_ram_gib": round(available_ram_gib, 2),
        "free_disk_gb": round(free_disk_gb, 2),
        "min_ram_threshold_gib": MIN_FREE_RAM_GIB,
        "min_disk_threshold_gb": MIN_FREE_DISK_GB,
        "ram_ok": ram_ok,
        "disk_ok": disk_ok,
        "can_process_jobs": ram_ok and disk_ok
    }
