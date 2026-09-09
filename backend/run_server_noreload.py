"""
Launch the API with no reloader, for tooling and demonstrations.

`run_server.py` uses reload=True, which is right while editing but spawns a
reloader parent plus a worker child. Signals sent to the parent leave the child
holding port 8000, and the surviving child keeps serving the module it imported
at start — so an edited route returns 404 and looks like a routing bug rather
than a stale process. One process, no reloader, no ambiguity.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000,
                reload=False, loop="asyncio")
