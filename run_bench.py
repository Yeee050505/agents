"""Benchmark server - sets env before any import"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["GLOBAL_RATE"] = "99999999"

import uvicorn
from main import app

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8005
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
