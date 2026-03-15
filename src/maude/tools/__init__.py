"""
MAUDE Tools — 80+ tools for file ops, web, shell, Google Workspace, GitHub,
browser automation, memory, collaboration, and more.

All public names are re-exported here:
    from maude.tools import TOOLS, execute_tool, get_tools_for_message
"""

# ── Logging ────────────────────────────────────────────────────
from .log import set_log_callback, log

# ── Paths ──────────────────────────────────────────────────────
from .paths import working_dir, set_working_directory, get_working_directory, resolve_path

# ── Cache ──────────────────────────────────────────────────────
from .cache import ToolCache, _tool_cache

# ── Rate Limits ────────────────────────────────────────────────
from .rate_limits import reset_rate_limits

# ── Tool Definitions ───────────────────────────────────────────
from .defs import TOOLS

# ── Tool Groups & Filtering ────────────────────────────────────
from .groups import (
    _CORE_TOOL_NAMES, _TOOL_GROUPS, _TOOL_BY_NAME, get_tools_for_message,
)

# ── Import tool modules to trigger @register_tool decorators ──
from . import file      # noqa: F401
from . import web       # noqa: F401
from . import ai        # noqa: F401
from . import memory    # noqa: F401
from . import github    # noqa: F401
from . import google    # noqa: F401
from . import substack  # noqa: F401
from . import collab    # noqa: F401
from . import shared    # noqa: F401
from . import agents    # noqa: F401
from . import schedule  # noqa: F401

# ── Execution ──────────────────────────────────────────────────
from .execute import execute_tool
