# MAUDE

AI assistant with 80+ tools. Cloud models, cross-platform, no GPU required.

```bash
pip install maude
maude
```

## Features

- **Cloud models**: Mistral, Claude, OpenAI, Gemini, Grok
- **80+ tools**: file ops, shell, web search, browser, Google Workspace, GitHub, Substack, memory
- **Cross-machine collaboration**: mesh networking, task dispatch
- **Rich TUI**: tool traces, streaming, native copy/paste
- **Setup wizard**: prompts for API keys on first run

## Quick Start

```bash
pip install maude
maude
```

On first run, MAUDE will prompt you for API keys. Mistral offers a free tier.

> **Note:** On some systems (e.g. Ubuntu/Debian), `pip` may point to Python 2. If `pip install maude` fails, use `pip3 install maude` instead.

## Models

| Name | Provider | Notes |
|------|----------|-------|
| mistral | Mistral AI | Default, good balance |
| claude | Anthropic | Claude Sonnet |
| claude-opus | Anthropic | Most capable |
| openai | OpenAI | GPT-4o |
| gemini | Google | Free tier |
| codestral | Mistral | Code-focused |
| devstral | Mistral | Dev-focused |

Switch models in chat: `/model claude`

## License

MIT
