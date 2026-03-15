"""
Collaboration tools — lazy-import registrations for mesh networking.
"""

from ..tool_registry import register_tool


def _get_collab_hub():
    """Get the collab hub singleton."""
    from ..collab.hub import get_hub
    return get_hub()


def execute_collab_tool(name: str, args: dict) -> str:
    """Execute a collaboration tool."""
    import json
    import time

    hub = _get_collab_hub()

    if name == "mesh_status":
        status = hub.get_status()
        lines = [f"Mesh Status ({status['hostname']}):\n"]

        presence = status.get("presence", [])
        if presence:
            lines.append("Online Devices:")
            for p in presence:
                activity = p.get("activity", "idle")
                lines.append(f"  - {p.get('hostname', '?')} ({p.get('platform', '?')}) — {activity}")
        else:
            lines.append("No devices online.")

        tasks = status.get("tasks", [])
        if tasks:
            lines.append(f"\nRecent Tasks ({len(tasks)}):")
            for t in tasks[:5]:
                lines.append(f"  [{t.get('status')}] {t.get('prompt', '')[:60]}")

        projects = status.get("projects", [])
        if projects:
            lines.append(f"\nProjects ({len(projects)}):")
            for p in projects[:5]:
                lines.append(f"  - {p.get('name', '?')}: {p.get('description', '')[:60]}")

        return "\n".join(lines)

    elif name == "dispatch_task":
        prompt = args.get("prompt", "")
        target = args.get("target", "")
        capability = args.get("capability", "LLM")

        if not prompt:
            return "Error: 'prompt' is required."

        task = hub.dispatch_task(prompt, target, capability)

        if task.get("status") == "failed":
            return f"Task failed: {task.get('result', 'unknown error')}"

        # Wait briefly for result
        task_id = task["id"]
        for _ in range(15):
            time.sleep(1)
            updated = hub.tasks.get(task_id)
            if updated and updated.get("status") in ("completed", "failed"):
                return f"[{updated['status']}] {updated.get('result', '(no output)')}"

        return f"Task dispatched (ID: {task_id}). Status: {task.get('status')}. Use list_tasks to check progress."

    elif name == "create_project":
        proj = hub.create_project(args.get("name", ""), args.get("description", ""))
        return f"Project created: {proj['name']} (ID: {proj['id']})"

    elif name == "list_projects":
        projects = hub.list_projects()
        if not projects:
            return "No projects."
        lines = [f"Projects ({len(projects)}):"]
        for p in projects:
            lines.append(f"  [{p['id']}] {p['name']}: {p.get('description', '')[:60]}")
        return "\n".join(lines)

    elif name == "add_to_project":
        success = hub.add_to_project(
            args.get("project_id", ""),
            conversation_id=args.get("conversation_id", ""),
            file_path=args.get("file_path", ""),
        )
        return "Added to project." if success else "Failed to add to project."

    elif name == "list_tasks":
        status_filter = args.get("status")
        tasks = hub.tasks.list_all(status=status_filter)
        if not tasks:
            return "No tasks."
        lines = [f"Tasks ({len(tasks)}):"]
        for t in tasks[:20]:
            lines.append(f"  [{t.get('status')}] {t.get('prompt', '')[:60]}")
        return "\n".join(lines)

    return f"Unknown collab tool: {name}"


@register_tool("mesh_status")
def _dispatch_mesh_status(args):
    return execute_collab_tool("mesh_status", args)

@register_tool("dispatch_task")
def _dispatch_dispatch_task(args):
    return execute_collab_tool("dispatch_task", args)

@register_tool("create_project")
def _dispatch_create_project(args):
    return execute_collab_tool("create_project", args)

@register_tool("list_projects")
def _dispatch_list_projects(args):
    return execute_collab_tool("list_projects", args)

@register_tool("add_to_project")
def _dispatch_add_to_project(args):
    return execute_collab_tool("add_to_project", args)

@register_tool("list_tasks")
def _dispatch_list_tasks(args):
    return execute_collab_tool("list_tasks", args)
