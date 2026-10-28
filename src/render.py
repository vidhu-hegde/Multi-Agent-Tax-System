"""Accessible, standalone HTML draft view over existing LineValue records; no tax calculations."""
import argparse
import json
from html import escape
from pathlib import Path

from src.schemas import FORM_LINES, LineValue


def draft_is_final(state: dict) -> bool:
    """Review passed and nothing is left open: the draft can be shown as current, and submitted."""
    return (state.get("status") == "draft_ready" and state.get("review_status") == "passed"
            and not state.get("revision_requests")
            and not any(getattr(t, "status", "open") == "open" for t in state.get("escalations", {}).values()))


def render_draft(state: dict) -> str:
    lines = {key: LineValue.model_validate(value) for key, value in state.get("lines", {}).items()}
    if any(key != value.line for key, value in lines.items()):
        raise ValueError("Line identity does not match its key")
    incomplete_documents = any(
        ref.form_type != "other" and (ref.document_id not in state.get("documents", {})
                                     or state.get("document_readiness", {}).get(ref.document_id) is False)
        for ref in state.get("document_inventory", [])
    )
    current = not incomplete_documents and draft_is_final(state)

    availability = {}

    def unavailable(key, path=()):
        if key in path:
            return "Calculation dependency cycle"
        if key in availability:
            return availability[key]
        if key not in lines:
            return "Calculation dependency missing"
        value = lines[key]
        if value.is_stub:
            availability[key] = "Pending real calculation (placeholder tool)"
            return availability[key]
        for parent in value.depends_on:
            reason = unavailable(parent, (*path, key))
            if reason:
                availability[key] = reason
                return reason
        availability[key] = None
        return None

    def trace(key, seen=None, root=None):
        # A fresh visited set belongs to each displayed line, not to the entire form.
        if seen is None:
            seen = {}
            root = key
        if key in seen or key not in lines:
            return ""
        node_id = f"audit-{root}-{len(seen)}"
        seen[key] = node_id
        value = lines[key]
        steps = []
        for step in value.provenance:
            source = escape(step.source)
            entered = f"; entered by {escape(step.entered_by)}" if step.entered_by else ""
            citation = f"; reference {escape(step.citation)}" if step.citation else ""
            inputs = ("<p>Calculation inputs: " + escape(json.dumps(step.model_dump(mode="json")["inputs"])) + "</p>"
                      if step.kind == "tool" else "")
            steps.append(f"<li><p><strong>{source}</strong>{entered}{citation}. Recorded {escape(step.recorded_at.isoformat())}.</p>"
                         + inputs + "<details><summary>Full audit record</summary><pre>"
                         + escape(step.model_dump_json(indent=2)) + "</pre></details></li>")
        steps = "".join(steps)
        parents = []
        for parent in value.depends_on:
            if parent in seen:
                parents.append(f'<li>Source line <a href="#{seen[parent]}">{escape(parent)}</a> (shown above)</li>')
            else:
                parents.append(f"<li>Source line {escape(parent)}{trace(parent, seen, root)}</li>")
        return f'<ol id="{node_id}" data-source-line="{escape(key, quote=True)}">{steps}{"".join(parents)}</ol>'

    rows = []
    for key, label in FORM_LINES.items():
        value = lines.get(key)
        reason = "Not supplied" if value is None else unavailable(key)
        if value is not None and not current:
            reason = "Pending review of current evidence"
        if reason:
            cell = f'<span class="pending">{escape(reason)}</span>'
        else:
            sources = "; ".join(p.source for p in value.provenance)
            cell = (f'<details id="line-{escape(key)}"><summary title="{escape(sources, quote=True)}">'
                    f'<span class="sr-only">Line {escape(key)}, {escape(label)}, </span>'
                    f'${value.amount:,.2f}<span class="hint"> Sources and calculation</span></summary>'
                    f'{trace(key)}</details>')
        rows.append(f'<tr><th scope="row">{escape(key)} &mdash; {escape(label)}</th><td>{cell}</td></tr>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>SilverFile draft 1040-SR, 2025</title><style>'
            'body{font:1.2rem/1.6 system-ui,sans-serif;color:#172638;background:#fff;max-width:75rem;margin:2rem auto;padding:1rem}'
            'table{border-collapse:collapse;width:100%}th,td{padding:1rem;border-bottom:1px solid #bbc5ce;text-align:left;vertical-align:top}'
            'summary{cursor:pointer;text-decoration:underline}summary:focus-visible{outline:3px solid #0759b0;outline-offset:4px}'
            '.hint,.pending{font-size:1rem}.pending{color:#694000}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:1rem}'
            '.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}'
            '@media(max-width:40rem){th,td{padding:.5rem}body{font-size:1rem}}'
            '@media print{details>*{display:block}summary{list-style:none}}'
            '</style></head><body><main><h1>Draft Form 1040-SR &mdash; 2025</h1>'
            '<p>Preparation aid for human review. This draft is not filed and provides no tax advice.</p>'
            '<p>Choose an amount to read its sources and calculation. Keyboard: Tab to the amount, then Enter or Space.</p>'
            '<p>Pending amounts are withheld until current evidence is reviewed and real calculations are available.</p>'
            '<table><caption>Supported return lines and their audit records</caption><thead><tr><th scope="col">Return line</th>'
            '<th scope="col">Amount and evidence</th></tr></thead><tbody>' + "".join(rows) +
            '</tbody></table></main></body></html>')


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render a synthetic case as an auditable HTML draft")
    parser.add_argument("--case", required=True)
    parser.add_argument("--output", type=Path, default=Path("output/draft_1040sr.html"))
    args = parser.parse_args(argv)
    from langgraph.checkpoint.memory import InMemorySaver
    from src.config import load_settings
    from src.graph import build_graph
    from src.memory import serializer, thread_config
    graph = build_graph(load_settings(), InMemorySaver(serde=serializer()))
    state = graph.invoke({"case_path": args.case}, thread_config())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_draft(state), encoding="utf-8")
    print(f"Draft written to {args.output}; pending/stub amounts withheld.")


if __name__ == "__main__":
    main()
