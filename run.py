"""SilverFile entry point.

    python run.py                        # start a new intake session
    python run.py --thread-id abc123     # resume a saved session
    python run.py --case demo/eval_case_1.md
    python run.py --batch [--no-context-strategy]

The graph itself lives in src/graph.py, which must expose:

    build_graph(settings, checkpointer, use_context_strategy=True) -> compiled LangGraph

When the graph pauses with interrupt(), this script shows the interrupt payload,
reads a reply from the terminal and resumes with Command(resume=reply).
"""

import argparse
import logging
import sys
import uuid
from contextlib import contextmanager

from src.config import load_settings

log = logging.getLogger("silverfile")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="SilverFile: Form 1040-SR preparation aid")
    parser.add_argument("--thread-id", help="resume a saved session (never use an SSN as the id)")
    parser.add_argument("--case", help="path to an eval case to run, e.g. demo/eval_case_1.md")
    parser.add_argument("--batch", action="store_true", help="run the batch scenario for docs/metrics.md")
    parser.add_argument(
        "--no-context-strategy",
        action="store_true",
        help="disable the context-window strategy (for the metrics comparison)",
    )
    return parser.parse_args(argv)


@contextmanager
def open_checkpointer(settings):
    from langgraph.checkpoint.sqlite import SqliteSaver

    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(settings.db_path)) as saver:
        yield saver


def load_graph(settings, checkpointer, use_context_strategy):
    try:
        from src.graph import build_graph
    except ImportError as exc:
        sys.exit(f"src/graph.py is not ready yet ({exc}). See README > Orchestration.")
    return build_graph(settings, checkpointer, use_context_strategy=use_context_strategy)


def drive(graph, thread_id, first_input, ask=input, say=print):
    """Run the graph on one thread, pausing for the user at every interrupt."""
    from langgraph.types import Command

    config = {"configurable": {"thread_id": thread_id}}
    payload = first_input
    while True:
        result = graph.invoke(payload, config)
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if not interrupts:
            return result
        for item in interrupts:
            say(item.value)
        try:
            payload = Command(resume=ask("> "))
        except (EOFError, KeyboardInterrupt):
            say(f"\nSession saved. Resume with: python run.py --thread-id {thread_id}")
            return None


def main(argv=None):
    args = parse_args(argv)
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")

    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    use_context_strategy = not args.no_context_strategy

    with open_checkpointer(settings) as checkpointer:
        graph = load_graph(settings, checkpointer, use_context_strategy)

        if args.batch:
            from src.graph import run_batch

            run_batch(graph, use_context_strategy=use_context_strategy)
            return

        if args.thread_id:
            thread_id, first_input = args.thread_id, None  # None resumes from the checkpoint
        else:
            thread_id = uuid.uuid4().hex[:12]
            first_input = {"case_path": args.case} if args.case else {}
            print(f"Session id: {thread_id}")

        drive(graph, thread_id, first_input)


if __name__ == "__main__":
    main()
