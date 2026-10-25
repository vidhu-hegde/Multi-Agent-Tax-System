"""Persistence: the SQLite checkpointer that makes sessions resumable.

Use open_checkpointer() everywhere (run.py, dashboard, tests) so every process can read every
session. Our Pydantic contracts are registered with the serializer explicitly; LangGraph will
refuse to load unregistered types from a checkpoint in a future version.
"""

import sqlite3
from contextlib import contextmanager

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from src.config import Settings
from src.schemas import Contract


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
        yield SqliteSaver(conn, serde=serializer())
    finally:
        conn.close()
