"""Entry point for `python -m maude` and the `maude` console script."""

import sys


def main():
    import argparse

    parser = argparse.ArgumentParser(prog="maude", description="MAUDE — AI assistant with 80+ tools")
    parser.add_argument("--serve", action="store_true", help="Start the HTTP gateway server")
    parser.add_argument("--port", type=int, default=None, help="Gateway port (default: 8080)")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--ssl-cert", default=None, help="Path to SSL certificate")
    parser.add_argument("--ssl-key", default=None, help="Path to SSL private key")
    parser.add_argument("--pwa-dir", default=None, help="Path to PWA static files directory")
    parser.add_argument("--setup", action="store_true", help="Run the setup wizard")

    args = parser.parse_args()

    from .keys import KeyManager
    km = KeyManager()
    km.load_all_keys()

    # Setup wizard
    if args.setup:
        from .setup_wizard import run_wizard
        run_wizard()
        return

    # Check if any provider is configured; if not, run setup wizard
    configured = km.list_configured()
    if not configured:
        from .setup_wizard import run_wizard
        run_wizard()
        configured = km.list_configured()
        if not configured:
            print("No API keys configured. Run `maude` again to set up.")
            sys.exit(1)

    # Gateway mode
    if args.serve:
        from .gateway import serve
        serve(port=args.port, ssl_cert=args.ssl_cert, ssl_key=args.ssl_key,
              pwa_dir=args.pwa_dir, bind=args.bind)
        return

    # Default: TUI mode
    from .tui import main as tui_main
    tui_main()


if __name__ == "__main__":
    main()
