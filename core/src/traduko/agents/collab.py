"""Multi-agent collaboration primitives: sessions, blackboard, messages.

v1 runs a single proofreading agent; these are the interface shapes the
design doc requires so hierarchical (master-slave) and peer
(master-master) topologies later compose from the same primitives:
sessions are rank-less identities, coordination happens only through the
shared blackboard and the message channel. Peer topologies must declare a
convergence protocol on top (agreement mark, max rounds, budget, or
arbiter) -- that logic lives with the topology, not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


class CollabError(Exception):
    pass


@dataclass
class AgentSession:
    id: str
    name: str
    tools: list[str] = field(default_factory=list)
    budget_usd: float | None = None


class Blackboard:
    """Shared state all agents of a task may read and write."""

    def __init__(self) -> None:
        self._data: dict = {}
        self._lock = Lock()

    def write(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value

    def read(self, key: str, default=None):
        with self._lock:
            return self._data.get(key, default)

    def keys(self) -> list[str]:
        with self._lock:
            return sorted(self._data)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)


class MessageChannel:
    """Point-to-point and broadcast messaging between registered sessions."""

    def __init__(self) -> None:
        self._mailboxes: dict[str, list[dict]] = {}
        self._lock = Lock()

    def register(self, agent_id: str) -> None:
        with self._lock:
            self._mailboxes.setdefault(agent_id, [])

    def send(self, sender: str, recipient: str, body: dict) -> None:
        with self._lock:
            if recipient not in self._mailboxes:
                raise CollabError(f"unknown recipient: {recipient}")
            self._mailboxes[recipient].append({"from": sender, "body": body})

    def broadcast(self, sender: str, body: dict) -> None:
        with self._lock:
            for agent_id, box in self._mailboxes.items():
                if agent_id != sender:
                    box.append({"from": sender, "body": body})

    def receive(self, agent_id: str) -> list[dict]:
        with self._lock:
            if agent_id not in self._mailboxes:
                raise CollabError(f"unknown agent: {agent_id}")
            messages = self._mailboxes[agent_id]
            self._mailboxes[agent_id] = []
            return messages
