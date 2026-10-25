"""The sample W-2s: generated from the IRS 2025 form, with test-range SSNs and matching ground truth."""

import json
import re
from pathlib import Path

import pymupdf

from data.generate_fixtures import W2S, generate

ROOT = Path(__file__).resolve().parent.parent


def test_generator_fills_the_form_with_the_expected_values(tmp_path):
    images = generate(demo_dir=tmp_path / "demo", fixtures_dir=tmp_path)
    assert [p.name for p in images] == ["w2_image_1.jpg", "w2_image_2.jpg"]

    for n, values in enumerate(W2S, start=1):
        page = pymupdf.open(tmp_path / f"w2_{n}.pdf")[0]
        filled = {w.field_name.split(".")[-1]: w.field_value for w in page.widgets()}
        assert filled["f2_01[0]"] == values["employee_ssn"]
        assert filled["f2_09[0]"] == values["box1_wages"]
        assert filled["f2_10[0]"] == values["box2_federal_withheld"]
        assert "2025" in page.get_text()


def test_committed_images_have_ground_truth_with_fake_identifiers():
    for n in (1, 2):
        assert (ROOT / "demo" / f"w2_image_{n}.jpg").exists()
        expected = json.loads((ROOT / "data" / "fixtures" / f"w2_{n}_expected.json").read_text())
        assert re.fullmatch(r"9\d{2}-\d{2}-\d{4}", expected["employee_ssn"])
        assert expected["employer_ein"].startswith("00-")


def test_ground_truth_is_a_valid_w2_record():
    from decimal import Decimal

    from src.schemas import Provenance, W2Record

    for n in (1, 2):
        expected = json.loads((ROOT / "data" / "fixtures" / f"w2_{n}_expected.json").read_text())
        image = expected.pop("image")
        record = W2Record(document_id=f"w2-{n}", source=Provenance(kind="document", source=image), **expected)
        assert record.wages == Decimal(expected["wages"])
        assert record.employee_ssn_last4 == expected["employee_ssn"][-4:]
