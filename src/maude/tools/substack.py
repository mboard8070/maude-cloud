"""
Substack tools — lazy-import registrations.
"""

from ..tool_registry import register_tool


def _substack_unavailable() -> str:
    return "Error: Substack integration not configured. See MAUDE docs for setup."


@register_tool("substack_create_draft")
def _dispatch_substack_create_draft(args):
    try:
        from ..integrations.substack import substack_create_draft
        return substack_create_draft(args.get("title", ""), args.get("body", ""), args.get("subtitle", ""), args.get("audience", "everyone"))
    except ImportError:
        return _substack_unavailable()

@register_tool("substack_list_drafts")
def _dispatch_substack_list_drafts(args):
    try:
        from ..integrations.substack import substack_list_drafts
        return substack_list_drafts(args.get("limit", 10))
    except ImportError:
        return _substack_unavailable()

@register_tool("substack_list_posts")
def _dispatch_substack_list_posts(args):
    try:
        from ..integrations.substack import substack_list_posts
        return substack_list_posts(args.get("limit", 10), args.get("offset", 0))
    except ImportError:
        return _substack_unavailable()

@register_tool("substack_get_post")
def _dispatch_substack_get_post(args):
    try:
        from ..integrations.substack import substack_get_post
        return substack_get_post(args.get("post_id", ""))
    except ImportError:
        return _substack_unavailable()

@register_tool("substack_update_draft")
def _dispatch_substack_update_draft(args):
    try:
        from ..integrations.substack import substack_update_draft
        return substack_update_draft(args.get("draft_id", ""), args.get("title"), args.get("body"), args.get("subtitle"))
    except ImportError:
        return _substack_unavailable()

@register_tool("substack_delete_draft")
def _dispatch_substack_delete_draft(args):
    try:
        from ..integrations.substack import substack_delete_draft
        return substack_delete_draft(args.get("draft_id", ""))
    except ImportError:
        return _substack_unavailable()

@register_tool("substack_get_stats")
def _dispatch_substack_get_stats(args):
    try:
        from ..integrations.substack import substack_get_stats
        return substack_get_stats()
    except ImportError:
        return _substack_unavailable()
