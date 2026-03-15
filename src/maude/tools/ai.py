"""
AI delegation tool — ask_frontier (escalate to a different cloud model).
"""

from .log import log
from ..tool_registry import register_tool


def tool_ask_frontier(question: str, context: str = None, provider: str = None) -> str:
    """Escalate a question to a frontier cloud model."""
    try:
        from ..providers import get_available_providers, PROVIDERS, Provider

        available = get_available_providers()
        if not available:
            return "Error: No providers configured. Set API keys with /keys set <provider> <key>"

        # Pick provider
        provider_name = provider if provider in available else None
        if not provider_name:
            # Prefer Claude, then OpenAI, then first available
            for pref in ("claude", "openai", "mistral"):
                if pref in available:
                    provider_name = pref
                    break
            if not provider_name:
                provider_name = next(iter(available))

        config = PROVIDERS[provider_name]
        log(f"Escalating to {provider_name}...")

        prompt = question
        if context:
            prompt = f"Context:\n{context}\n\nQuestion:\n{question}"

        if config.provider == Provider.ANTHROPIC:
            import anthropic
            from ..providers import get_api_key
            client = anthropic.Anthropic(api_key=get_api_key(provider_name))
            response = client.messages.create(
                model=config.default_model,
                max_tokens=4096,
                system="You are an expert assistant. Be thorough but concise.",
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
            return f"[Expert response from {provider_name}]\n\n{content}"

        else:
            from openai import OpenAI
            from ..providers import get_api_key
            client = OpenAI(api_key=get_api_key(provider_name), base_url=config.base_url)
            response = client.chat.completions.create(
                model=config.default_model,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": "You are an expert assistant. Be thorough but concise."},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content
            return f"[Expert response from {provider_name}]\n\n{content}"

    except Exception as e:
        return f"Error calling frontier model: {e}"


@register_tool("ask_frontier")
def _dispatch_ask_frontier(args):
    return tool_ask_frontier(args.get("question", ""), args.get("context"), args.get("provider"))
