"""Generate the sample W-2 images used by the demo and the extraction tests.

    python data/generate_fixtures.py

Fills Copy B of the official IRS 2025 Form W-2 (data/fixtures/fw2_2025_blank.pdf, downloaded from
https://www.irs.gov/pub/irs-prior/fw2--2025.pdf) with invented data, and writes for each W-2:

    demo/w2_image_N.jpg               the image a user (or grader) uploads
    data/fixtures/w2_N.pdf            the filled PDF
    data/fixtures/w2_N_expected.json  ground truth: what extraction should read from the image

Every person and employer is fictional. SSNs are in the IRS test range (900-999) and EINs start
with 00, which the IRS never issues.
"""

import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
BLANK = ROOT / "data" / "fixtures" / "fw2_2025_blank.pdf"
BLANK_URL = "https://www.irs.gov/pub/irs-prior/fw2--2025.pdf"
COPY_B_PAGE = 3  # zero-based page index of "Copy B - To Be Filed With Employee's Federal Tax Return"
CROP_BOTTOM = 384  # points; keeps the form and its title line, drops the instructions below
DPI = 200

# Copy B field name (last part) -> key in the W-2 definitions below
FIELDS = {
    "f2_01[0]": "employee_ssn",  # box a
    "f2_02[0]": "employer_ein",  # box b
    "f2_03[0]": "employer_name_address",  # box c
    "f2_04[0]": "control_number",  # box d
    "f2_05[0]": "employee_first_name",  # box e
    "f2_06[0]": "employee_last_name",
    "f2_08[0]": "employee_address",  # box f
    "f2_09[0]": "box1_wages",
    "f2_10[0]": "box2_federal_withheld",
    "f2_11[0]": "box3_social_security_wages",
    "f2_12[0]": "box4_social_security_withheld",
    "f2_13[0]": "box5_medicare_wages",
    "f2_14[0]": "box6_medicare_withheld",
    "f2_20[0]": "box12a_code",
    "f2_21[0]": "box12a_amount",
    "c2_3[0]": "box13_retirement_plan",
    "f2_29[0]": "box15_state",
    "f2_30[0]": "box15_employer_state_id",
    "f2_33[0]": "box16_state_wages",
    "f2_35[0]": "box17_state_withheld",
}

W2S = [
    {
        # Eval case 1: clean run.
        "employee_ssn": "901-23-4567",
        "employer_ein": "00-1234567",
        "employer_name_address": "Finger Lakes Hardware Co.\n410 E State St\nIthaca, NY 14850",
        "control_number": "FLH-0192",
        "employee_first_name": "Margaret A",
        "employee_last_name": "Ellis",
        "employee_address": "212 Lakeview Rd\nIthaca, NY 14850",
        "box1_wages": "18000.00",
        "box2_federal_withheld": "1500.00",
        "box3_social_security_wages": "18000.00",
        "box4_social_security_withheld": "1116.00",
        "box5_medicare_wages": "18000.00",
        "box6_medicare_withheld": "261.00",
        "box15_state": "NY",
        "box15_employer_state_id": "00-1234567",
        "box16_state_wages": "18000.00",
        "box17_state_withheld": "720.00",
    },
    {
        # Eval case 2: the taxpayer tells Intake a different wage figure, so user and document conflict.
        "employee_ssn": "902-45-6789",
        "employer_ein": "00-7654321",
        "employer_name_address": "Cayuga Community Library\n101 N Cayuga St\nIthaca, NY 14850",
        "control_number": "CCL-0457",
        "employee_first_name": "Harold J",
        "employee_last_name": "Brennan",
        "employee_address": "88 Cascadilla St\nIthaca, NY 14850",
        "box1_wages": "26450.00",
        "box2_federal_withheld": "2380.00",
        "box3_social_security_wages": "27450.00",
        "box4_social_security_withheld": "1701.90",
        "box5_medicare_wages": "27450.00",
        "box6_medicare_withheld": "398.03",
        "box12a_code": "D",
        "box12a_amount": "1000.00",
        "box13_retirement_plan": True,
        "box15_state": "NY",
        "box15_employer_state_id": "00-7654321",
        "box16_state_wages": "26450.00",
        "box17_state_withheld": "1190.25",
    },
]


def ensure_blank() -> Path:
    if not BLANK.exists():
        import urllib.request

        urllib.request.urlretrieve(BLANK_URL, BLANK)
    return BLANK


def fill_w2(values: dict) -> pymupdf.Document:
    doc = pymupdf.open(ensure_blank())
    doc.select([COPY_B_PAGE])
    page = doc[0]
    for widget in page.widgets():
        key = FIELDS.get(widget.field_name.split(".")[-1])
        if key is None or key not in values:
            continue
        value = values[key]
        widget.field_value = (widget.on_state() if value else "Off") if isinstance(value, bool) else value
        widget.update()
    return doc


def expected_record(values: dict) -> dict:
    """What the Document Extraction agent should produce from this image."""
    return {
        "form_type": "W-2",
        "employer_name": values["employer_name_address"].splitlines()[0],
        "employer_ein": values["employer_ein"],
        "employee_name": f"{values['employee_first_name']} {values['employee_last_name']}",
        "employee_ssn": values["employee_ssn"],
        "wages": values["box1_wages"],
        "federal_withheld": values["box2_federal_withheld"],
        "social_security_wages": values["box3_social_security_wages"],
        "social_security_withheld": values["box4_social_security_withheld"],
        "medicare_wages": values["box5_medicare_wages"],
        "medicare_withheld": values["box6_medicare_withheld"],
        "retirement_plan": values.get("box13_retirement_plan", False),
    }


def generate(demo_dir: Path = ROOT / "demo", fixtures_dir: Path = ROOT / "data" / "fixtures") -> list[Path]:
    demo_dir.mkdir(parents=True, exist_ok=True)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for n, values in enumerate(W2S, start=1):
        doc = fill_w2(values)
        page = doc[0]
        pdf_path = fixtures_dir / f"w2_{n}.pdf"
        doc.save(pdf_path, garbage=4, deflate=True)

        clip = pymupdf.Rect(0, 0, page.rect.width, CROP_BOTTOM)
        image_path = demo_dir / f"w2_image_{n}.jpg"
        page.get_pixmap(dpi=DPI, clip=clip).save(image_path, jpg_quality=90)
        images.append(image_path)

        expected = {"image": f"demo/{image_path.name}", **expected_record(values)}
        (fixtures_dir / f"w2_{n}_expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    return images


if __name__ == "__main__":
    for path in generate():
        print(f"wrote {path.relative_to(ROOT)}")
