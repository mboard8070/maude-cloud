"""
Schedule tool — schedule_task.
"""

from ..tool_registry import register_tool


@register_tool("schedule_task")
def _dispatch_schedule_task(args):
    return "schedule_task is not yet available in the cloud-only package."
