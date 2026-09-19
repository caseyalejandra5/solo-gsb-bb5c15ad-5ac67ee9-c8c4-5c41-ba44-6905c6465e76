import datetime as dt

from fastapi.testclient import TestClient

from app.gs1 import parse_element_string
from app.main import app

client = TestClient(app)
GS = "\x1d"


def gtin14(body13: str) -> str:
    """Append the correct GS1 Mod-10 check digit to a 13-digit body."""
    total = sum(
        int(d) * (3 if i % 2 == 0 else 1)
        for i, d in enumerate(reversed(body13))
    )
    return body13 + str((10 - total % 10) % 10)


GTIN = gtin14("0950600013435")  # 09506000134352


def post(data: str):
    return client.post("/parse", json={"data": data})


# ---------- happy paths ----------

def test_full_string_preserves_order():
    r = post(f"01{GTIN}17251231{GS}10ABC123{GS}21XYZ789")
    assert r.status_code == 200
    elements = r.json()["elements"]
    assert [e["ai"] for e in elements] == ["01", "17", "10", "21"]
    assert elements[0] == {
        "ai": "01", "title": "GTIN", "value": GTIN, "offset": 0,
    }
    assert elements[1]["value"] == "251231"
    assert elements[1]["date"] == "2025-12-31"
    assert elements[2]["value"] == "ABC123"
    assert elements[3]["value"] == "XYZ789"


def test_byte_offsets_of_elements():
    r = post(f"01{GTIN}17251231{GS}10ABC")
    elements = r.json()["elements"]
    assert [e["offset"] for e in elements] == [0, 16, 25]


def test_fixed_length_fields_self_delimit_without_separator():
    r = post(f"01{GTIN}17251231")
    assert r.status_code == 200
    assert [e["ai"] for e in r.json()["elements"]] == ["01", "17"]


def test_variable_field_at_end_needs_no_separator():
    r = post("21SERIAL-0001")
    assert r.status_code == 200
    assert r.json()["elements"][0]["value"] == "SERIAL-0001"


def test_optional_separator_after_fixed_length_field():
    r = post(f"01{GTIN}{GS}17251231")
    assert r.status_code == 200
    assert [e["ai"] for e in r.json()["elements"]] == ["01", "17"]


def test_max_length_variable_fields():
    r = post(f"10{'B' * 20}{GS}21{'s' * 20}")
    assert r.status_code == 200
    values = [e["value"] for e in r.json()["elements"]]
    assert values == ["B" * 20, "s" * 20]


def test_day_00_means_last_day_of_month():
    r = post("17250200")
    assert r.status_code == 200
    assert r.json()["elements"][0]["date"] == "2025-02-28"


def test_leap_day_is_a_real_date():
    r = post("17240229")
    assert r.status_code == 200
    assert r.json()["elements"][0]["date"] == "2024-02-29"


def test_year_sliding_window():
    # GS1 window around 2026: 49 years back / 50 years forward.
    el = parse_element_string("17761231", today=dt.date(2026, 6, 1))[0]
    assert el.date == dt.date(2076, 12, 31)
    el = parse_element_string("17770101", today=dt.date(2026, 6, 1))[0]
    assert el.date == dt.date(1977, 1, 1)


# ---------- errors: 422 with byte offset and rule ----------

def check_error(resp, code, offset):
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == code
    assert detail["offset"] == offset
    assert detail["rule"]
    assert detail["message"]


def test_empty_input():
    check_error(post(""), "EMPTY_INPUT", 0)


def test_unknown_ai():
    check_error(post("99ABC"), "UNKNOWN_AI", 0)


def test_leading_separator():
    check_error(post(f"{GS}21ABC"), "STRAY_SEPARATOR", 0)


def test_trailing_separator():
    check_error(post(f"21ABC{GS}"), "TRAILING_SEPARATOR", 5)


def test_truncated_fixed_field():
    check_error(post("01012345"), "TRUNCATED_FIELD", 0)


def test_invalid_character_in_numeric_field():
    # 'A' at char index 15 -> byte offset 15
    check_error(post("010950600013435A"), "INVALID_CHARACTER", 15)


def test_invalid_character_reports_byte_not_char_offset():
    # 'é' is 2 bytes in UTF-8 and starts at byte offset 4
    check_error(post("10ABé"), "INVALID_CHARACTER", 4)


def test_wrong_gtin_check_digit():
    bad = GTIN[:-1] + str((int(GTIN[-1]) + 1) % 10)
    check_error(post(f"01{bad}"), "INVALID_CHECK_DIGIT", 15)


def test_variable_field_too_long():
    # 21st character of the batch starts at byte offset 2 + 20
    check_error(post("10" + "A" * 21), "FIELD_TOO_LONG", 22)


def test_empty_variable_field():
    check_error(post(f"10{GS}17251231"), "FIELD_TOO_SHORT", 2)


def test_impossible_date():
    check_error(post("17250230"), "INVALID_DATE", 2)


def test_impossible_month():
    check_error(post("17251301"), "INVALID_DATE", 2)


def test_missing_body_is_422():
    r = client.post("/parse", json={})
    assert r.status_code == 422


def test_health():
    assert client.get("/health").json() == {"status": "ok"}
