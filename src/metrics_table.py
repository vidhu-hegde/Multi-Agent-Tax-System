"""The docs/metrics.md results table from the two context-benchmark runs (run.py --batch [--no-context-strategy]).

    python -m src.metrics_table output/context_on.json output/context_off.json [--out docs/metrics]

Prints the ten markdown rows (strategy ON and OFF input tokens, both outcomes) and the first-to-last growth
of each series, to paste into docs/metrics.md. --out copies the two raw result files into a directory so they
can be committed (output/ is gitignored). It reports the numbers as measured; it never estimates or fills gaps.
"""

import argparse
import json
import shutil
from pathlib import Path

ITEMS = 10
HEADER = (
    "| Sequential item | Strategy ON input tokens | Strategy OFF input tokens | Live outcome check |\n"
    "|---|---|---|---|"
)


def load(path, strategy_enabled: bool) -> dict:
    run = json.loads(Path(path).read_text())
    label = "ON" if strategy_enabled else "OFF"
    if run.get("strategy_enabled") is not strategy_enabled:
        raise ValueError(f"{path} is not a strategy {label} run (strategy_enabled={run.get('strategy_enabled')!r})")
    numbers = [row.get("item") for row in run.get("items", [])]
    if numbers != list(range(1, ITEMS + 1)):
        raise ValueError(f"{path} must hold items 1-{ITEMS} in order, found {numbers}")
    for row in run["items"]:
        if type(row.get("input_tokens")) is not int or type(row.get("correct")) is not bool:
            raise ValueError(f"{path} item {row['item']} has no measured input_tokens or outcome")
    return run


def growth(label: str, items: list[dict]) -> str:
    first, last = items[0]["input_tokens"], items[-1]["input_tokens"]
    change = f"{(last - first) / first:+.0%}" if first else "n/a"
    return f"{label}: {first:,} → {last:,} input tokens ({last - first:+,}, {change})"


def table(on: dict, off: dict) -> str:
    if on.get("model") != off.get("model"):
        raise ValueError(f"The runs used different models: ON {on.get('model')!r}, OFF {off.get('model')!r}")
    rows = [HEADER]
    for a, b in zip(on["items"], off["items"]):
        outcome = (f"ON {'correct' if a['correct'] else 'incorrect'}, "
                   f"OFF {'correct' if b['correct'] else 'incorrect'}")
        rows.append(f"| {a['item']} | {a['input_tokens']:,} | {b['input_tokens']:,} | {outcome} |")
    return "\n".join([
        *rows,
        "",
        f"First to last item. {growth('ON', on['items'])}; {growth('OFF', off['items'])}.",
        f"Model {on['model']}. ON thread {on['thread_id']} ({on['measured_at']}); "
        f"OFF thread {off['thread_id']} ({off['measured_at']}).",
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Markdown results table for docs/metrics.md")
    parser.add_argument("on", type=Path, help="strategy ON results, e.g. output/context_on.json")
    parser.add_argument("off", type=Path, help="strategy OFF results, e.g. output/context_off.json")
    parser.add_argument("--out", type=Path, help="also copy both result files here, e.g. docs/metrics")
    args = parser.parse_args(argv)
    try:
        on, off = load(args.on, True), load(args.off, False)
        text = table(on, off)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for source, name in ((args.on, "context_on.json"), (args.off, "context_off.json")):
            shutil.copyfile(source, args.out / name)
    print(text)


if __name__ == "__main__":
    main()
