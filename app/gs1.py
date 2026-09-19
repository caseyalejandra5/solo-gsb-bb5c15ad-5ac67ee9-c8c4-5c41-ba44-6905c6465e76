"""GS1 element string parser.

Supports AI 01 (GTIN-14), 10 (batch/lot), 17 (expiry date) and 21 (serial).
Fixed-length fields are self-delimiting; a variable-length field must be
terminated by the ASCII 29 (GS) separator unless it is the last element.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

GS = "\x1d"  # ASCII 29 (group separator), the GS1 field separator

#: GS1 AI encodable character set ("set 82", GS1 General Specifications
#: figure 7.11-1): digits, upper/lowercase letters and 20 symbols.
AI_CHARSET_82 = frozenset(
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "!\"%&'()*+,-./:;<=>?_"
)

DIGITS = frozenset("0123456789")


@dataclass(frozen=True)
class AISpec:
    ai: str
    title: str
    fixed_length: int | None  # exact length for fixed-length fields, else None
    max_length: int
    numeric_only: bool


AI_SPECS: dict[str, AISpec] = {
    spec.ai: spec
    for spec in (
        AISpec("01", "GTIN", fixed_length=14, max_length=14, numeric_only=True),
        AISpec("10", "BATCH/LOT", fixed_length=None, max_length=20, numeric_only=False),
        AISpec("17", "USE BY OR EXPIRY", fixed_length=6, max_length=6, numeric_only=True),
        AISpec("21", "SERIAL", fixed_length=None, max_length=20, numeric_only=False),
    )
}


class GS1ParseError(Exception):
    """Parse/validation failure carrying a byte offset and the expected rule."""

    def __init__(self, code: str, message: str, offset: int, rule: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.offset = offset  # byte offset into the UTF-8 encoded input
        self.rule = rule

    def to_dict(self) -> dict:
        return {
            "error": self.code,
            "message": self.message,
            "offset": self.offset,
            "rule": self.rule,
        }


@dataclass
class Element:
    ai: str
    title: str
    value: str
    offset: int  # byte offset of the AI within the input
    date: dt.date | None = None  # normalized date, AI 17 only


def parse_element_string(data: str, *, today: dt.date | None = None) -> list[Element]:
    """Parse a raw GS1 element string into an ordered list of elements.

    Raises GS1ParseError on the first violation found.
    """
    today = today or dt.date.today()
    offsets = _byte_offsets(data)
    n = len(data)
    if n == 0:
        raise GS1ParseError(
            "EMPTY_INPUT",
            "input is empty",
            0,
            "expected at least one element: AI (2 digits) followed by its value",
        )

    elements: list[Element] = []
    pos = 0
    while pos < n:
        ai_offset = offsets[pos]
        if data[pos] == GS:
            raise GS1ParseError(
                "STRAY_SEPARATOR",
                "separator (ASCII 29) must appear only between elements",
                ai_offset,
                "expected an AI (2 digits) here",
            )
        ai = data[pos : pos + 2]
        spec = AI_SPECS.get(ai)
        if spec is None:
            raise GS1ParseError(
                "UNKNOWN_AI",
                f"unsupported AI {ai!r}",
                ai_offset,
                "expected one of the supported AIs: 01, 10, 17, 21",
            )
        pos += 2
        field_start = pos

        if spec.fixed_length is not None:
            end = field_start + spec.fixed_length
            if end > n:
                raise GS1ParseError(
                    "TRUNCATED_FIELD",
                    f"AI ({ai}) needs exactly {spec.fixed_length} characters, "
                    f"only {n - field_start} left",
                    ai_offset,
                    f"AI ({ai}) {spec.title} is fixed length {spec.fixed_length}",
                )
            value = data[field_start:end]
            pos = end
            # A separator after a fixed-length field is not required but tolerated.
            terminated = pos < n and data[pos] == GS
            if terminated:
                pos += 1
        else:
            gs_at = data.find(GS, field_start)
            terminated = gs_at != -1
            end = gs_at if terminated else n
            value = data[field_start:end]
            pos = end + 1 if terminated else n

        parsed_date = _validate_value(spec, value, offsets, field_start, today)
        elements.append(
            Element(ai=spec.ai, title=spec.title, value=value,
                    offset=ai_offset, date=parsed_date)
        )

        if terminated and pos == n:
            raise GS1ParseError(
                "TRAILING_SEPARATOR",
                "input ends with a separator (ASCII 29)",
                offsets[n - 1],
                "a separator must be followed by the next AI",
            )

    return elements


def _validate_value(
    spec: AISpec,
    value: str,
    offsets: list[int],
    field_start: int,
    today: dt.date,
) -> dt.date | None:
    """Validate charset, length and AI-specific semantics of one value."""
    length_rule = (
        f"AI ({spec.ai}) {spec.title} allows 1 to {spec.max_length} characters"
    )
    if spec.fixed_length is None and len(value) == 0:
        raise GS1ParseError(
            "FIELD_TOO_SHORT",
            f"AI ({spec.ai}) requires at least 1 character",
            offsets[field_start],
            length_rule,
        )

    charset = DIGITS if spec.numeric_only else AI_CHARSET_82
    allowed = (
        "digits 0-9"
        if spec.numeric_only
        else "the GS1 AI character set (digits, letters, !\"%&'()*+,-./:;<=>?_)"
    )
    for i, ch in enumerate(value):
        if ch not in charset:
            raise GS1ParseError(
                "INVALID_CHARACTER",
                f"character {ch!r} (U+{ord(ch):04X}) is not allowed in AI ({spec.ai})",
                offsets[field_start + i],
                f"AI ({spec.ai}) {spec.title} accepts only {allowed}",
            )

    if spec.fixed_length is None and len(value) > spec.max_length:
        raise GS1ParseError(
            "FIELD_TOO_LONG",
            f"AI ({spec.ai}) allows at most {spec.max_length} characters, "
            f"got {len(value)}",
            offsets[field_start + spec.max_length],
            length_rule,
        )

    if spec.ai == "01":
        ok, expected = _gtin_check_ok(value)
        if not ok:
            raise GS1ParseError(
                "INVALID_CHECK_DIGIT",
                f"GTIN check digit mismatch: expected {expected}, got {value[-1]}",
                offsets[field_start + len(value) - 1],
                "AI (01) GTIN must carry a valid GS1 Mod-10 check digit",
            )
    if spec.ai == "17":
        return _parse_expiry(value, offsets[field_start], today)
    return None


def _gtin_check_ok(gtin: str) -> tuple[bool, int]:
    """GS1 Mod-10 check: weights 3/1 alternating from the right of the body."""
    total = sum(
        int(d) * (3 if i % 2 == 0 else 1)
        for i, d in enumerate(reversed(gtin[:-1]))
    )
    expected = (10 - total % 10) % 10
    return expected == int(gtin[-1]), expected


def _parse_expiry(yymmdd: str, offset: int, today: dt.date) -> dt.date:
    rule = "AI (17) must be a real date in YYMMDD (day 00 = last day of month)"
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if not 1 <= mm <= 12:
        raise GS1ParseError(
            "INVALID_DATE", f"month {mm:02d} does not exist", offset, rule
        )
    # GS1 sliding window (Gen. Specs 7.12): the date must fall between
    # 49 years in the past and 50 years in the future.
    year = today.year // 100 * 100 + yy
    if year > today.year + 50:
        year -= 100
    elif year < today.year - 49:
        year += 100
    last_day = calendar.monthrange(year, mm)[1]
    if dd == 0:
        dd = last_day  # GS1: day 00 means the last day of the month
    elif dd > last_day:
        raise GS1ParseError(
            "INVALID_DATE",
            f"{year:04d}-{mm:02d} has no day {dd:02d}",
            offset,
            rule,
        )
    return dt.date(year, mm, dd)


def _byte_offsets(s: str) -> list[int]:
    """Byte offset (UTF-8) of every character index, plus the end offset."""
    offsets = [0] * (len(s) + 1)
    total = 0
    for i, ch in enumerate(s):
        offsets[i] = total
        total += len(ch.encode("utf-8"))
    offsets[len(s)] = total
    return offsets
