"""python -m src.dashboard [--demo] [--port 8000]"""

import argparse
import sys
from dataclasses import replace

import uvicorn

from src.config import ROOT, load_settings
from src.dashboard.app import create_app
from src.dashboard.demo import seed
from src.sessions import open_sessions
from src.tools import TaxMathUnavailable, check_server


def main(argv=None):
    parser = argparse.ArgumentParser(description="SilverFile staff dashboard")
    parser.add_argument("--demo", action="store_true",
                        help="use a separate demo database (output/demo.sqlite), seeded with returns in every state")
    parser.add_argument("--host", default="127.0.0.1", help="interface to listen on (default: this machine only)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    settings = load_settings()
    try:
        check_server()  # before seeding, which runs the demo returns through tax_math
    except TaxMathUnavailable as exc:
        sys.exit(str(exc))
    if args.demo:
        # Offline and repeatable: the demo never calls the model or touches the real database.
        settings = replace(settings, anthropic_api_key="", db_path=ROOT / "output" / "demo.sqlite")
        with open_sessions(settings) as sessions:
            started = seed(sessions, ROOT / "output" / "demo_cases")
        print(f"Demo database: {settings.db_path} ({len(started)} new returns)")
    uvicorn.run(create_app(settings=settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
