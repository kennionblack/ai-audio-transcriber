"""Compatibility launcher for VoxAI."""

from __future__ import annotations

import uvicorn

from web_app import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
