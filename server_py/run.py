#!/usr/bin/env python3
"""Run the Chat with Hootie server."""
import uvicorn
from config import CONFIG

if __name__ == "__main__":
    print(f"🚀 Starting Chat with Hootie server on port {CONFIG.PORT}")
    print(f"📡 Provider: {CONFIG.PROVIDER}")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=CONFIG.PORT,
        reload=True
    )

