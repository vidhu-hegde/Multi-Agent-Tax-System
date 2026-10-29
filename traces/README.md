# Recorded runs of the two graded eval cases

This folder holds both graded walkthroughs, run offline with no key and
with the tax math on the MCP server. Each `_state.json` is the final saved state: answers, documents, rule
decisions with citations, every line with its provenance (each tool step's `via` is the server URL) and
the agent handoffs. Each `_draft.html` is the finished draft: open it in a browser and click any amount for its sources.

| File | Shows |
|---|---|
| `demo_eval-case-1-clean-run_state.json`, `_draft.html` | The clean return (typed W-2): `draft_ready`, refund $2,455.50 |
| `demo_eval-case-2-wage-conflict_ticket.json` | The escalation staff saw: stated wages $24,000 against the W-2's $26,450.00 |
| `demo_eval-case-2-wage-conflict_state.json`, `_draft.html` | The same return after staff chose Continue: the resolved ticket and a refund of $1,460.25 |

No full SSN appears: case 2's W-2 keeps only the last four digits of the fixture's test SSN. To regenerate
(timestamps change; everything else is the same):

```bash
python -m src.tax_math.server &   # stop it afterwards
TAX_MATH_MCP_URL=http://localhost:8001/mcp python -m evals.run_evals --case eval-case-1-clean-run --trace traces
TAX_MATH_MCP_URL=http://localhost:8001/mcp python -m evals.run_evals --case eval-case-2-wage-conflict --trace traces
```
