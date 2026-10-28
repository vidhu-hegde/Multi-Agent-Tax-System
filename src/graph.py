"""The SilverFile graph: a hub-and-spoke topology with the orchestrator at the centre.

Every agent returns to the orchestrator, which picks the next hop from state (conditional routing).
Document extraction fans out with Send, one branch per document, and joins at aggregate_documents.
The review -> revise cycle and the loop guard are enforced inside the orchestrator.

Agents can be swapped (e.g. in tests) by passing build_graph(..., agents={"intake": my_intake}).
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.agents.computation import computation
from src.agents.extraction import aggregate_documents, extract_document, make_extraction
from src.agents.human import human
from src.agents.intake import intake
from src.agents.orchestrator import make_orchestrator, pending_documents
from src.agents.review import review
from src.agents.rules import rules
from src.config import Settings
from src.communication import checked_agent
from src.state import SilverFileState

DEFAULT_AGENTS = {
    "intake": intake,
    "extraction": extract_document,
    "rules": rules,
    "computation": computation,
    "review": review,
}


def route(state: SilverFileState):
    next_agent = state["next_agent"]
    if next_agent == "end":
        return END
    if next_agent == "extraction":
        requested = {r.document_id for r in state.get("revision_requests", []) if r.target == "extraction"}
        return [
            Send("extract_document", {
                "doc": ref,
                "revision_epoch": state.get("evidence_epoch", 0) + 1 if ref.document_id in requested else None,
            })
            for ref in pending_documents(state)
        ]
    return next_agent


def build_graph(settings: Settings, checkpointer=None, use_context_strategy: bool = True, agents: dict | None = None):
    # use_context_strategy is passed to the LLM-backed agents once they exist (docs/metrics.md).
    agents = {**DEFAULT_AGENTS, "extraction": make_extraction(settings), **(agents or {})}
    builder = StateGraph(SilverFileState)

    builder.add_node("orchestrator", checked_agent("orchestrator", make_orchestrator(settings)))
    builder.add_node("intake", checked_agent("intake", agents["intake"]))
    builder.add_node("extract_document", checked_agent("extraction", agents["extraction"]))
    builder.add_node("aggregate_documents", checked_agent("aggregate_documents", aggregate_documents))
    builder.add_node("rules", checked_agent("rules", agents["rules"]))
    builder.add_node("computation", checked_agent("computation", agents["computation"]))
    builder.add_node("review", checked_agent("review", agents["review"]))
    builder.add_node("human", checked_agent("human", human))

    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges(
        "orchestrator",
        route,
        ["intake", "extract_document", "rules", "computation", "review", "human", END],
    )
    builder.add_edge("extract_document", "aggregate_documents")
    for node in ("aggregate_documents", "intake", "rules", "computation", "review", "human"):
        builder.add_edge(node, "orchestrator")

    return builder.compile(checkpointer=checkpointer)


def run_batch(graph, use_context_strategy: bool = True):
    raise SystemExit("The batch scenario is not implemented yet (see docs/metrics.md).")
