"""
First-run setup wizard — prompts for API keys interactively.
"""

import sys
from .keys import KeyManager
from .providers import PROVIDERS


def run_wizard():
    """Interactive first-run setup wizard."""
    print()
    print("=" * 60)
    print("  MAUDE — First-Time Setup")
    print("=" * 60)
    print()
    print("MAUDE needs at least one API key to work.")
    print("You can add more later with /keys set <provider> <key>")
    print()
    print("Supported providers:")
    print()

    providers_list = [
        ("mistral", "Mistral AI", "Free tier available — https://console.mistral.ai/"),
        ("claude", "Anthropic Claude", "https://console.anthropic.com/"),
        ("openai", "OpenAI", "https://platform.openai.com/"),
        ("gemini", "Google Gemini", "Free tier — https://aistudio.google.com/"),
        ("grok", "xAI Grok", "https://console.x.ai/"),
    ]

    for i, (key, name, url) in enumerate(providers_list, 1):
        print(f"  {i}. {name:20s} {url}")

    print()
    print("Paste an API key for any provider (or press Enter to skip):")
    print()

    km = KeyManager()

    for key, name, url in providers_list:
        try:
            api_key = input(f"  {name} API key: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            break

        if api_key:
            if km.set_key(key, api_key):
                print(f"    + Saved {name} key")
            else:
                print(f"    x Failed to save {name} key")
        else:
            print(f"    - Skipped")

    configured = km.list_configured()
    print()
    if configured:
        print(f"Setup complete! {len(configured)} provider(s) configured: {', '.join(configured)}")
        print("Run `maude` to start chatting.")
    else:
        print("No keys configured. You can set them later with:")
        print("  maude  (will re-run this wizard)")
        print("  or set environment variables (MISTRAL_API_KEY, ANTHROPIC_API_KEY, etc.)")
    print()
