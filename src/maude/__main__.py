"""Entry point for `python -m maude` and the `maude` console script."""

import sys
import socket
import subprocess
from urllib.error import URLError
from urllib.request import urlopen


def _base_url(gateway: str) -> str:
    gateway = gateway.rstrip("/")
    if gateway.endswith("/v1"):
        return gateway[:-3].rstrip("/")
    return gateway


def _run_doctor(gateway: str) -> int:
    from . import __version__
    from .keys import KeyManager
    from .providers import PROVIDERS, get_api_key

    KeyManager().load_all_keys()
    base = _base_url(gateway)
    checks = [
        ("maude", __version__),
        ("python", sys.version.split()[0]),
        ("platform", sys.platform),
        ("hostname", socket.gethostname()),
        ("gateway", base),
    ]

    try:
        with urlopen(f"{base}/health", timeout=5) as resp:
            checks.append(("gateway health", f"ok HTTP {resp.status}"))
    except URLError as exc:
        checks.append(("gateway health", f"unreachable: {exc.reason}"))
    except Exception as exc:
        checks.append(("gateway health", f"unreachable: {exc}"))

    for name, command in {
        "git": ["git", "--version"],
        "gh": ["gh", "--version"],
        "playwright": ["playwright", "--version"],
    }.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            output = result.stdout or result.stderr
            first = output.splitlines()[0] if output else "installed"
            checks.append((name, first if result.returncode == 0 else "not ready"))
        except FileNotFoundError:
            checks.append((name, "not installed"))
        except Exception as exc:
            checks.append((name, f"error: {exc}"))

    for name in PROVIDERS:
        checks.append((f"provider:{name}", "configured" if get_api_key(name) else "not configured"))

    width = max(len(name) for name, _ in checks)
    for name, value in checks:
        print(f"{name:<{width}}  {value}")
    return 0


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
    parser.add_argument("--doctor", action="store_true", help="Check local dependencies, providers, and gateway")
    parser.add_argument("--gateway", default="http://127.0.0.1:8080/v1", help="Gateway URL for --doctor")

    args = parser.parse_args()

    from .keys import KeyManager
    km = KeyManager()
    km.load_all_keys()

    if args.doctor:
        return _run_doctor(args.gateway)

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
