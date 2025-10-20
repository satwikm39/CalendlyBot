"""Vercel serverless entrypoint for the Calendly Scheduling FastAPI app.

Vercel looks for a file inside the `api/` directory that exports a WSGI/ASGI
application object named `app`. We import the existing FastAPI app from
`server` and expose it.
"""

import os
import sys

# Ensure project root is on sys.path so we can import `server` cleanly when
# deployed by Vercel (which executes from the `api/` dir).
repo_root = os.path.dirname(os.path.dirname(__file__))
if repo_root not in sys.path:
    sys.path.append(repo_root)

from server import app  # noqa: E402  pylint: disable=wrong-import-position

# Vercel's Python runtime will pick up this `app` variable automatically.

