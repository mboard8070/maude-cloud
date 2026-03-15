"""
Memory tools — persistent key-value memory for cross-session recall.
"""

import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

from ..tool_registry import register_tool
from .log import log


@dataclass
class MemoryEntry:
    key: str
    value: str
    category: str = "fact"
    created: float = field(default_factory=time.time)


class SimpleMemory:
    """JSON-file-backed memory store."""

    def __init__(self, path: Path = None):
        if path is None:
            path = Path.home() / ".config" / "maude" / "memory.json"
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                for k, v in data.items():
                    self._entries[k] = MemoryEntry(**v) if isinstance(v, dict) else MemoryEntry(key=k, value=str(v))
            except Exception:
                pass

    def _save(self):
        data = {}
        for k, entry in self._entries.items():
            data[k] = {"key": entry.key, "value": entry.value, "category": entry.category, "created": entry.created}
        self._path.write_text(json.dumps(data, indent=2))

    def remember(self, key: str, value: str, category: str = "fact"):
        self._entries[key] = MemoryEntry(key=key, value=value, category=category)
        self._save()

    def search(self, query: str, limit: int = 5, category: str = None) -> List[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            if category and entry.category != category:
                continue
            if query_lower in entry.key.lower() or query_lower in entry.value.lower():
                results.append(entry)
        return results[:limit]

    def list_memories(self, category: str = None, limit: int = 20) -> List[MemoryEntry]:
        entries = list(self._entries.values())
        if category:
            entries = [e for e in entries if e.category == category]
        entries.sort(key=lambda e: e.created, reverse=True)
        return entries[:limit]

    def forget(self, key: str) -> bool:
        if key in self._entries:
            del self._entries[key]
            self._save()
            return True
        return False

    def save_message(self, session_id: str, role: str, content: str, channel: str = "cli"):
        pass  # Conversation sync handled separately

    def get_conversation(self, session_id: str, limit: int = 10):
        return []


# Singleton
_memory: Optional[SimpleMemory] = None


def get_memory() -> Optional[SimpleMemory]:
    global _memory
    if _memory is None:
        try:
            _memory = SimpleMemory()
        except Exception as e:
            log(f"Memory init failed: {e}")
            return None
    return _memory


# ── Registry wrappers ──────────────────────────────────────────

@register_tool("save_memory")
def _dispatch_save_memory(args):
    mem = get_memory()
    if not mem:
        return "Error: Memory system unavailable."
    key = args.get("key", "").strip()
    value = args.get("value", "").strip()
    category = args.get("category", "fact")
    if not key or not value:
        return "Error: Both 'key' and 'value' are required."
    mem.remember(key, value, category)
    log(f"Memory saved: [{category}] {key}")
    return f"Remembered [{category}] {key}: {value}"


@register_tool("recall_memory")
def _dispatch_recall_memory(args):
    mem = get_memory()
    if not mem:
        return "Error: Memory system unavailable."
    query = args.get("query", "").strip()
    category = args.get("category")
    if not query:
        return "Error: 'query' is required."
    results = mem.search(query, limit=5, category=category)
    if not results:
        return f"No memories found matching '{query}'."
    lines = [f"Found {len(results)} relevant memories:"]
    for m in results:
        lines.append(f"- [{m.category}] **{m.key}**: {m.value}")
    return "\n".join(lines)


@register_tool("list_memories")
def _dispatch_list_memories(args):
    mem = get_memory()
    if not mem:
        return "Error: Memory system unavailable."
    category = args.get("category")
    limit = args.get("limit", 20)
    memories = mem.list_memories(category=category, limit=limit)
    if not memories:
        return "No memories stored." if not category else f"No memories in category '{category}'."
    lines = [f"Stored memories ({len(memories)}):"]
    for m in memories:
        lines.append(f"- [{m.category}] **{m.key}**: {m.value}")
    return "\n".join(lines)


@register_tool("forget_memory")
def _dispatch_forget_memory(args):
    mem = get_memory()
    if not mem:
        return "Error: Memory system unavailable."
    key = args.get("key", "").strip()
    if not key:
        return "Error: 'key' is required."
    if mem.forget(key):
        log(f"Memory forgotten: {key}")
        return f"Forgot: {key}"
    return f"No memory found for '{key}'."
