"""Run the API locally:  python run_local.py   ->  http://localhost:8000/docs

On Windows, psycopg's async driver needs the selector event loop, so we start uvicorn ourselves.
In Docker/Linux (Hugging Face Spaces, Render) the normal `uvicorn app.main:app` command is used.
"""
import asyncio
import os
import sys

import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)                      # so `app.main` resolves no matter where this is launched from
sys.path.insert(0, HERE)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000"))))
    asyncio.run(server.serve())
