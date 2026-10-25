"""Memory boundaries: opaque workflow identity, selective disclosure and restart persistence."""

import pytest

from src import memory


def test_thread_identity_is_opaque_stable_and_rejects_ssns():
    a, b = memory.thread_config(), memory.thread_config()
    assert a != b
    identifier = a['configurable']['thread_id']
    assert memory.thread_config(identifier) == a
    for value in ('901-12-3456', '123456789', 'return-901-12-3456'):
        with pytest.raises(ValueError, match='thread'):
            memory.thread_config(value)


def test_sqlite_boundary_rejects_ssn_identifiers(settings):
    with memory.open_checkpointer(settings) as saver:
        with pytest.raises(ValueError, match='thread'):
            saver.get_tuple({'configurable': {'thread_id': '901-12-3456'}})
