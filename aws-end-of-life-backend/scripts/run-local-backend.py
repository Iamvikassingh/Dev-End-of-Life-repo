#!/usr/bin/env python3
"""
AWS EOL Monitor — Local backend server (REAL logic, no AWS required).

Wraps api_handler.lambda_handler in Flask so the React frontend can call
real endpoints, including GET /eol/general which fetches live data from
endoflife.date.

Storage uses STORAGE_BACKEND=file by default — data is persisted to
/tmp/eol-data/ on disk. No DynamoDB, S3, or AWS credentials needed.

Usage:
    cd /path/to/end_of_life
    pip install flask flask-cors requests --break-system-packages
    python3 scripts/run-local-backend.py

    # Or via Makefile:
    make backend

Then set in frontend/.env.local:
    REACT_APP_API_URL=http://localhost:3001
    REACT_APP_ENABLE_DEMO_DATA=false
"""
import json
import logging
import os
import sys

os.environ.setdefault("STORAGE_BACKEND",  "file")
os.environ.setdefault("EOL_DATA_DIR",     "/tmp/eol-data")
os.environ.setdefault("WARN_DAYS",        "180")
os.environ.setdefault("GENERAL_EOL_CACHE_TTL_HOURS", "24")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
# Add backend/ to path so api_handler and its imports resolve correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

try:
    from flask import Flask, request, Response
    from flask_cors import CORS
except ImportError:
    print("Missing dependencies. Run:")
    print("  pip install flask flask-cors requests --break-system-packages")
    sys.exit(1)

import api_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("local-backend")

app = Flask(__name__)
CORS(app, origins="*")

PORT = int(os.environ.get("PORT", 3001))


def _build_event(req):
    """Convert a Flask request to an API Gateway Lambda proxy event dict."""
    body = req.get_data(as_text=True) or "{}"
    return {
        "httpMethod":            req.method,
        "path":                  req.path,
        "queryStringParameters": dict(req.args) or None,
        "headers":               dict(req.headers),
        "body":                  body,
        "isBase64Encoded":       False,
    }


@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/", methods=["GET", "OPTIONS"])
def proxy(path=""):
    event = _build_event(request)
    logger.info("%s /%s", request.method, path)
    try:
        result = api_handler.lambda_handler(event, None)
    except Exception as exc:
        logger.exception("Handler error: %s", exc)
        result = {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}}),
        }
    return Response(
        result.get("body", ""),
        status=result.get("statusCode", 200),
        headers=result.get("headers", {}),
    )


if __name__ == "__main__":
    os.makedirs(os.environ["EOL_DATA_DIR"], exist_ok=True)

    # Warm the general EOL cache in background if it is empty.
    # This way the first GET /eol/general returns instantly from cache,
    # rather than blocking for 15–30s waiting on endoflife.date.
    from storage import get_storage as _get_storage
    import general_eol as _geol
    _storage = _get_storage()
    _cached  = _storage.get_general_eol_cache()
    if not _cached or not _cached.get("records"):
        logger.info("Cache empty — starting background warm (takes ~15s)")
        _geol.warm_cache_background(_storage)
        _cache_status = "empty — warming in background (~15s)"
    else:
        _n = len(_cached["records"])
        _cache_status = f"warm ({_n} records)"

    # Admin token info for startup banner
    _token_file = os.path.join(os.environ["EOL_DATA_DIR"], "secrets", "initial-admin-token")
    if os.environ.get("ADMIN_PORTAL_TOKEN"):
        _admin_status = "set via ADMIN_PORTAL_TOKEN env var"
    else:
        _admin_status = f"cat {_token_file}"

    print(f"""
╔══════════════════════════════════════════════════════╗
║        AWS EOL Monitor — Local Backend               ║
╠══════════════════════════════════════════════════════╣
║  URL:      http://localhost:{PORT:<26}║
║  Storage:  {os.environ['STORAGE_BACKEND']:<42}║
║  Data dir: {os.environ['EOL_DATA_DIR']:<42}║
║  Cache:    {_cache_status:<42}║
║  Admin:    {_admin_status:<42}║
╠══════════════════════════════════════════════════════╣
║  Endpoints:                                          ║
║    GET  /eol/general       ← cache-first, instant   ║
║    GET  /eol/general/summary                        ║
║    POST /eol/general/refresh  ← fetches endoflife   ║
║    GET  /eol/inventory                              ║
║    GET  /eol/summary                                ║
║    GET  /eol/alerts                                 ║
║    GET  /eol/config                                 ║
║    PUT  /eol/config                                 ║
╠══════════════════════════════════════════════════════╣
║  If /general-eol shows empty:                       ║
║    curl -X POST http://localhost:{PORT}/eol/general/refresh ║
╚══════════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=PORT, debug=False)
