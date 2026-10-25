"""Persistence: the SQLite checkpointer that makes sessions resumable.

Use open_checkpointer() everywhere (run.py, dashboard, tests) so every process can read every
session. Our Pydantic contracts are registered with the serializer explicitly; LangGraph will
refuse to load unregistered types from a checkpoint in a future version.
"""

import sqlite3
import re
import uuid
from contextlib import contextmanager

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from src.config import Settings
from src.schemas import Contract


def thread_config(thread_id: str | None = None) -> dict:
    """Identify one return with an opaque id, never a taxpayer's SSN."""
    if thread_id is None:
        opaque = uuid.uuid4().hex
        thread_id = "return-" + "-".join(opaque[i:i + 4] for i in range(0, 32, 4))
    if not isinstance(thread_id, str) or not thread_id.strip() or re.search(r"\d{3}-\d{2}-\d{4}|\d{9}", thread_id):
        raise ValueError("Use a non-SSN thread id for this return")
    return {"configurable": {"thread_id": thread_id}}


class WorkflowSqliteSaver(SqliteSaver):
    """Enforce non-SSN identity for existing CLI and dashboard callers too."""

    def get_tuple(self, config):
        thread_config(config["configurable"]["thread_id"])
        return super().get_tuple(config)

    def put(self, config, checkpoint, metadata, new_versions):
        thread_config(config["configurable"]["thread_id"])
        return super().put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        thread_config(config["configurable"]["thread_id"])
        return super().put_writes(config, writes, task_id, task_path)


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def serializer() -> JsonPlusSerializer:
    contracts = {(c.__module__, c.__name__) for c in _all_subclasses(Contract)}
    return JsonPlusSerializer(allowed_msgpack_modules=sorted(contracts))


@contextmanager
def open_checkpointer(settings: Settings):
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the Streamlit dashboard calls in from worker threads; SqliteSaver locks.
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    try:
        yield WorkflowSqliteSaver(conn, serde=serializer())
    finally:
        conn.close()
