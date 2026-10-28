"""Live check: read each committed W-2 image with Claude and compare every field with its expected record.

    python -m evals.live_vision_check

Needs ANTHROPIC_API_KEY in .env (never printed). Without it the check is skipped. It sends one request
per image through the same read_w2() the Extraction agent uses, so a pass here means the graph reads
the W-2 correctly too. Unlike the graph, which hides provider errors behind a staff ticket, this prints
why a read failed, so the prompt or image can be fixed.
"""

import json
import sys
from decimal import Decimal, InvalidOperation

from anthropic import Anthropic

from src.agents.extraction import read_w2
from src.config import ROOT, load_settings
from src.schemas import DocumentRef

CASES = [("w2-1", ROOT / "data/fixtures/w2_1_expected.json"), ("w2-2", ROOT / "data/fixtures/w2_2_expected.json")]


def same(expected, got) -> bool:
    """Equal as values: amounts compare as numbers at any depth, so box 12's "1000.00" matches 1000.0."""
    if isinstance(expected, dict) and isinstance(got, dict):
        return expected.keys() == got.keys() and all(same(value, got[key]) for key, value in expected.items())
    if isinstance(expected, list) and isinstance(got, list):
        return len(expected) == len(got) and all(same(a, b) for a, b in zip(expected, got))
    try:
        return Decimal(str(expected)) == Decimal(str(got))
    except (InvalidOperation, ValueError, TypeError):
        return expected == got


def check(document_id, expected_path, client, model) -> bool:
    expected = json.loads(expected_path.read_text())
    ref = DocumentRef(document_id=document_id, form_type="W-2", image_path=expected["image"])
    try:
        record = read_w2(ref, client, model)
    except Exception as exc:  # report and move on; the graph would raise a staff ticket here
        print(f"FAIL  {expected['image']}: could not read ({type(exc).__name__}: {exc})")
        return False
    got = record.model_dump(mode="json")
    wrong = []
    for field, want in expected.items():
        if field == "image":
            continue
        if field == "employee_ssn":  # the record keeps only the last four digits
            field, want = "employee_ssn_last4", want[-4:] if want else None
        if not same(want, got.get(field)):
            wrong.append(f"{field}: expected {want!r}, read {got.get(field)!r}")
    checked = len(expected) - 1
    print(f"{'PASS' if not wrong else 'FAIL'}  {expected['image']}: {checked - len(wrong)} of {checked} fields "
          f"match (model {got['source']['inputs']['model']})")
    for line in wrong:
        print(f"      - {line}")
    return not wrong


def main() -> int:
    settings = load_settings()
    if not settings.anthropic_api_key:
        print("Skipped: set ANTHROPIC_API_KEY in .env to run the live W-2 check.")
        return 0
    client = Anthropic(api_key=settings.anthropic_api_key, max_retries=0, timeout=60)
    results = [check(document_id, path, client, settings.model) for document_id, path in CASES]
    print(f"\n{sum(results)} of {len(results)} W-2 images read correctly")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
