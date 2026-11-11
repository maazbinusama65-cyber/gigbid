"""python -m gigsim  -> serve GigSim on GIGSIM_HOST:GIGSIM_PORT (default 127.0.0.1:8081)."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("gigsim.app:app", host=os.environ.get("GIGSIM_HOST", "127.0.0.1"),
                port=int(os.environ.get("GIGSIM_PORT", "8081")), log_level="info")
