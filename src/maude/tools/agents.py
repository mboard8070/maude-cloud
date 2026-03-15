"""
Agent dispatch tool — run_agent, run_agents.

These tools let the main LLM dispatch tasks to the engine recursively
with their own tool access.
"""

from .log import log
from ..tool_registry import register_tool


@register_tool("run_agent")
def _dispatch_run_agent(args):
    agent_name = args.get("agent", "")
    task = args.get("task", "")
    context = args.get("context", "")

    if not agent_name or not task:
        return "Error: 'agent' and 'task' are required"

    log(f"Dispatching to {agent_name} agent: {task[:60]}...")

    # Use the engine to run a sub-turn
    try:
        from ..engine import run_agent_task
        result = run_agent_task(agent_name, task, context)
        return f"[{agent_name} agent]\n\n{result}"
    except ImportError:
        return f"Error: Agent execution not available in this context."
    except Exception as e:
        return f"[{agent_name} agent error] {e}"


@register_tool("run_agents")
def _dispatch_run_agents(args):
    tasks_data = args.get("tasks", [])
    if not tasks_data:
        return "Error: 'tasks' array is required"

    import concurrent.futures

    def _run_one(t):
        agent_name = t.get("agent", "")
        task = t.get("task", "")
        context = t.get("context", "")
        try:
            from ..engine import run_agent_task
            result = run_agent_task(agent_name, task, context)
            return f"### {agent_name} agent\n\n{result}"
        except Exception as e:
            return f"### {agent_name} agent (error)\n{e}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_run_one, t) for t in tasks_data]
        results = [f.result() for f in futures]

    return "\n\n---\n\n".join(results)
