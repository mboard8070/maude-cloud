"""
MAUDE Collaboration Hub — Presence, activity feed, projects, task dispatch.

Adapted from the terminal-llm collab.py for standalone package use.
Storage: JSON files in ~/.config/maude/data/collab/
"""

import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR


# ── Storage helpers ──────────────────────────────────────────────

COLLAB_DIR = DATA_DIR / "collab"
PROJECTS_DIR = COLLAB_DIR / "projects"
TASKS_DIR = COLLAB_DIR / "tasks"

for _d in (COLLAB_DIR, PROJECTS_DIR, TASKS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MY_HOSTNAME = socket.gethostname().lower()


def _atomic_write(path: Path, data: Any):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, default=str))
    tmp.rename(path)


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default if default is not None else {}


# ── Presence Manager ─────────────────────────────────────────────

class PresenceManager:
    STALE_THRESHOLD = 90

    def __init__(self):
        self._lock = threading.Lock()
        self._file = COLLAB_DIR / "presence.json"
        self._clients: Dict[str, dict] = {}
        self._load()

    def _load(self):
        stored = _read_json(self._file, [])
        if isinstance(stored, list):
            for entry in stored:
                cid = entry.get("client_id")
                if cid:
                    self._clients[cid] = entry

    def heartbeat(self, client_id: str, client_type: str = "tui",
                  activity: str = "", conversation_id: str = "",
                  project_id: str = "", hostname: str = "",
                  platform: str = ""):
        with self._lock:
            self._clients[client_id] = {
                "client_id": client_id,
                "client_type": client_type,
                "hostname": hostname or MY_HOSTNAME,
                "platform": platform or client_type,
                "status": "active",
                "activity": activity,
                "active_conversation": conversation_id,
                "last_seen": time.time(),
            }
            self._prune()
            self._save()

    def get_all(self) -> List[dict]:
        with self._lock:
            self._prune()
            return list(self._clients.values())

    def _prune(self):
        now = time.time()
        stale = [k for k, v in self._clients.items()
                 if now - v.get("last_seen", 0) > self.STALE_THRESHOLD]
        for k in stale:
            del self._clients[k]

    def _save(self):
        _atomic_write(self._file, list(self._clients.values()))


# ── Activity Feed ────────────────────────────────────────────────

class ActivityFeed:
    def __init__(self):
        self._lock = threading.Lock()

    def _today_file(self) -> Path:
        return COLLAB_DIR / f"activity-{time.strftime('%Y-%m-%d')}.jsonl"

    def emit(self, event_type: str, summary: str, data: dict = None,
             client_id: str = "", conversation_id: str = ""):
        event = {
            "id": f"evt-{uuid.uuid4().hex[:12]}",
            "ts": time.time(),
            "hostname": MY_HOSTNAME,
            "client_id": client_id,
            "type": event_type,
            "summary": summary,
            "data": data or {},
        }
        with self._lock:
            with open(self._today_file(), "a") as f:
                f.write(json.dumps(event, default=str) + "\n")

    def get_recent(self, limit: int = 50) -> List[dict]:
        events = []
        for days_ago in range(2):
            ts = time.time() - days_ago * 86400
            path = COLLAB_DIR / f"activity-{time.strftime('%Y-%m-%d', time.localtime(ts))}.jsonl"
            if path.exists():
                try:
                    for line in path.read_text().strip().split("\n"):
                        if line:
                            events.append(json.loads(line))
                except Exception:
                    pass
        events.sort(key=lambda e: e.get("ts", 0), reverse=True)
        return events[:limit]


# ── Project Manager ──────────────────────────────────────────────

class ProjectManager:
    def __init__(self):
        self._lock = threading.Lock()

    def create(self, name: str, description: str = "") -> dict:
        proj = {
            "id": f"proj-{uuid.uuid4().hex[:12]}",
            "name": name,
            "description": description,
            "created_at": time.time(),
            "updated_at": time.time(),
            "hostname": MY_HOSTNAME,
            "conversations": [],
            "files": [],
        }
        with self._lock:
            _atomic_write(PROJECTS_DIR / f"{proj['id']}.json", proj)
        return proj

    def get(self, project_id: str) -> Optional[dict]:
        safe_id = project_id.replace("/", "").replace("..", "")
        return _read_json(PROJECTS_DIR / f"{safe_id}.json", None)

    def list_all(self) -> List[dict]:
        projects = []
        for f in PROJECTS_DIR.glob("proj-*.json"):
            proj = _read_json(f, None)
            if proj:
                projects.append(proj)
        projects.sort(key=lambda p: p.get("updated_at", 0), reverse=True)
        return projects

    def add_conversation(self, project_id: str, conversation_id: str) -> bool:
        proj = self.get(project_id)
        if not proj:
            return False
        if conversation_id not in proj["conversations"]:
            proj["conversations"].append(conversation_id)
            proj["updated_at"] = time.time()
            with self._lock:
                _atomic_write(PROJECTS_DIR / f"{project_id}.json", proj)
        return True

    def add_file(self, project_id: str, file_path: str) -> bool:
        proj = self.get(project_id)
        if not proj:
            return False
        if file_path not in proj["files"]:
            proj["files"].append(file_path)
            proj["updated_at"] = time.time()
            with self._lock:
                _atomic_write(PROJECTS_DIR / f"{project_id}.json", proj)
        return True


# ── Task Dispatcher ──────────────────────────────────────────────

class TaskDispatcher:
    def __init__(self):
        self._lock = threading.Lock()

    def create(self, prompt: str, target: str = "", capability: str = "LLM",
               project_id: str = "", target_client_id: str = "",
               target_platform: str = "") -> dict:
        is_client_targeted = bool(target_client_id or target_platform)
        task = {
            "id": f"task-{uuid.uuid4().hex[:12]}",
            "source": MY_HOSTNAME,
            "target": target,
            "target_client_id": target_client_id,
            "target_platform": target_platform,
            "capability": capability,
            "status": "queued" if is_client_targeted else "pending",
            "prompt": prompt,
            "result": None,
            "project_id": project_id,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with self._lock:
            _atomic_write(TASKS_DIR / f"{task['id']}.json", task)
        return task

    def get(self, task_id: str) -> Optional[dict]:
        safe_id = task_id.replace("/", "").replace("..", "")
        return _read_json(TASKS_DIR / f"{safe_id}.json", None)

    def update_status(self, task_id: str, status: str, result: str = None) -> Optional[dict]:
        task = self.get(task_id)
        if not task:
            return None
        task["status"] = status
        if result is not None:
            task["result"] = result
        task["updated_at"] = time.time()
        with self._lock:
            _atomic_write(TASKS_DIR / f"{task_id}.json", task)
        return task

    def list_all(self, status: str = None) -> List[dict]:
        tasks = []
        for f in TASKS_DIR.glob("task-*.json"):
            task = _read_json(f, None)
            if task:
                if status and task.get("status") != status:
                    continue
                tasks.append(task)
        tasks.sort(key=lambda t: t.get("created_at", 0), reverse=True)
        return tasks

    def execute(self, task_dict: dict) -> str:
        task_id = task_dict.get("id")
        prompt = task_dict.get("prompt", "")
        capability = task_dict.get("capability", "LLM")

        with self._lock:
            _atomic_write(TASKS_DIR / f"{task_id}.json", task_dict)
        self.update_status(task_id, "running")

        try:
            if capability == "SHELL":
                result = subprocess.run(
                    prompt, shell=True, capture_output=True, text=True, timeout=60
                )
                output = result.stdout or result.stderr or "(no output)"
                self.update_status(task_id, "completed", output)
                return output
            else:
                from ..tools.execute import execute_tool
                result = execute_tool("run_command", {"command": prompt})
                self.update_status(task_id, "completed", str(result))
                return str(result)
        except Exception as e:
            self.update_status(task_id, "failed", str(e))
            return f"Error: {e}"


# ── CollabHub (Singleton) ────────────────────────────────────────

class CollabHub:
    def __init__(self):
        self.presence = PresenceManager()
        self.activity = ActivityFeed()
        self.projects = ProjectManager()
        self.tasks = TaskDispatcher()

    def heartbeat(self, client_id: str, client_type: str = "tui",
                  activity: str = "", conversation_id: str = "",
                  hostname: str = "", platform: str = ""):
        self.presence.heartbeat(client_id, client_type, activity,
                                conversation_id, hostname=hostname, platform=platform)

    def emit(self, event_type: str, summary: str, data: dict = None,
             client_id: str = "", conversation_id: str = ""):
        self.activity.emit(event_type, summary, data, client_id, conversation_id)

    def get_status(self) -> dict:
        return {
            "hostname": MY_HOSTNAME,
            "ts": time.time(),
            "presence": self.presence.get_all(),
            "activity": self.activity.get_recent(),
            "projects": self.projects.list_all(),
            "tasks": self.tasks.list_all(),
        }

    def dispatch_task(self, prompt: str, target: str = "",
                      capability: str = "LLM", project_id: str = "",
                      target_client_id: str = "", target_platform: str = "") -> dict:
        task = self.tasks.create(
            prompt, target, capability, project_id,
            target_client_id=target_client_id,
            target_platform=target_platform,
        )
        self.emit("task_dispatched", f"Dispatched task: {prompt[:50]}")

        if not target and not target_client_id and not target_platform:
            threading.Thread(target=self.tasks.execute, args=(task,), daemon=True).start()

        return task

    def create_project(self, name: str, description: str = "") -> dict:
        proj = self.projects.create(name, description)
        self.emit("project_created", f"Created project: {name}")
        return proj

    def list_projects(self) -> List[dict]:
        return self.projects.list_all()

    def add_to_project(self, project_id: str, conversation_id: str = "",
                       file_path: str = "") -> bool:
        if conversation_id:
            return self.projects.add_conversation(project_id, conversation_id)
        if file_path:
            return self.projects.add_file(project_id, file_path)
        return False


# ── Module-level singleton ───────────────────────────────────────

_hub: Optional[CollabHub] = None
_hub_lock = threading.Lock()


def get_hub() -> CollabHub:
    global _hub
    if _hub is None:
        with _hub_lock:
            if _hub is None:
                _hub = CollabHub()
    return _hub
