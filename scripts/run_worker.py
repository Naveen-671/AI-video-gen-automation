"""Script to run the database-backed worker loop."""

import logging
from backend.app.worker.runner import WorkerRunner
from backend.app.db.connection import init_db
from backend.app.config import DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    init_db(DB_PATH)
    worker = WorkerRunner()
    print(f"Starting worker {worker.worker_id} on database {DB_PATH}")
    worker.run_forever()
