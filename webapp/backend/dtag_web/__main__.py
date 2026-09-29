"""Launch the DTAG web application: ``python -m dtag_web``."""
from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="DTAG web application")
    ap.add_argument("--host", default=os.environ.get("DTAG_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("DTAG_PORT", "8000")))
    ap.add_argument("--reload", action="store_true", help="development auto-reload")
    args = ap.parse_args(argv)

    import uvicorn

    uvicorn.run("dtag_web.app:app", host=args.host, port=args.port, reload=args.reload, workers=1)


if __name__ == "__main__":
    main()
