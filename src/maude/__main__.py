"""Entry point for `python -m maude` and the `maude` console script."""

import sys


def main():
    from .keys import KeyManager
    from .providers import PROVIDERS

    km = KeyManager()
    km.load_all_keys()

    # Check if any provider is configured; if not, run setup wizard
    configured = km.list_configured()
    if not configured:
        from .setup_wizard import run_wizard
        run_wizard()
        configured = km.list_configured()
        if not configured:
            print("No API keys configured. Run `maude` again to set up.")
            sys.exit(1)

    from .tui import main as tui_main
    tui_main()


if __name__ == "__main__":
    main()
