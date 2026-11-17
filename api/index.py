"""Vercel entry point: the Django API served as a Python (WSGI) function.

Every request under /api/* is rewritten here by vercel.json; Django routes on the original path (/api/v1/...).
The React SPA is served by Vercel as static files from frontend/dist (same origin, no CORS).
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
