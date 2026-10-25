import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.config import load_settings
from src.graph import build_graph

SKELETON_CASE = "data/fixtures/skeleton_case.json"


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def make_graph(settings):
    def make(agents=None, checkpointer=None):
        return build_graph(settings, checkpointer or InMemorySaver(), agents=agents)

    return make
