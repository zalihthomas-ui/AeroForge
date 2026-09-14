"""Design Agent for AeroForge.

Parses natural language and structured engineering requirements into an
EngineeringSpec that can be consumed by downstream agents (e.g. Geometry Agent).
"""

from __future__ import annotations

import re
from typing import Any

from engineering.requirements.schema import (
    Constraint,
    EngineeringSpec,
    Objective,
    Requirement,
)


class UnrecognizedRequirementError(ValueError):
    """Raised when an engineering requirement cannot be parsed or is unsupported."""

    pass


# Mapping for word-based numbers up to twenty
_WORD_TO_NUM: dict[str, int] = {
    "zero": 0,
    "no": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}

_NUM_WORDS_PATTERN = (
    r"(?:zero|no|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|\d+)"
)

# Regex patterns for dimensions
_DIM_3WAY_PATTERN = re.compile(
    r"(?P<l>\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:[xX*×\u00d7]|\bby\b)\s*"
    r"(?P<w>\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:[xX*×\u00d7]|\bby\b)\s*"
    r"(?P<t>\d+(?:\.\d+)?)\s*(?:mm)?",
    re.IGNORECASE,
)

_LENGTH_NAMED_PATTERN = re.compile(
    r"\b(?:length|len|l)\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.IGNORECASE,
)
_WIDTH_NAMED_PATTERN = re.compile(
    r"\b(?:width|w)\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.IGNORECASE,
)
_THICKNESS_NAMED_PATTERN = re.compile(
    r"\b(?:thickness|thick|t|height|h|depth|d)\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.IGNORECASE,
)

# Regex patterns for holes
_HOLE_COUNT_DIAM_PATTERN = re.compile(
    rf"\b(?P<count>{_NUM_WORDS_PATTERN})\s*(?:x|-)?\s*(?P<diam>\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:mounting\s*)?holes?\b",
    re.IGNORECASE,
)

_HOLE_COUNT_THEN_DIAM_PATTERN = re.compile(
    rf"\b(?P<count>{_NUM_WORDS_PATTERN})\s*(?:mounting\s*)?holes?\s*(?:with|of|having|each)?\s*(?:a\s*)?"
    r"(?:diameter\s*(?:of|is|:)?\s*)?(?P<diam>\d+(?:\.\d+)?)\s*(?:mm)?(?:\s*diameter|\s*diam|\s*dia)?\b",
    re.IGNORECASE,
)

_NO_HOLES_PATTERN = re.compile(
    r"\b(?:no|without|zero|0)\s*(?:mounting\s*)?holes?\b",
    re.IGNORECASE,
)

_HOLE_COUNT_EXPLICIT_PATTERN = re.compile(
    rf"\b(?:hole[_\s]*count|num[_\s]*holes)\s*[:=]?\s*(?P<val>{_NUM_WORDS_PATTERN})\b",
    re.IGNORECASE,
)

_HOLE_DIAM_EXPLICIT_PATTERN = re.compile(
    r"\b(?:hole[_\s]*diameter|hole[_\s]*diam|hole[_\s]*size)\s*[:=]?\s*(?P<val>\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.IGNORECASE,
)


def _parse_count_or_num(token: str) -> float:
    token_clean = token.strip().lower()
    if token_clean in _WORD_TO_NUM:
        return float(_WORD_TO_NUM[token_clean])
    try:
        return float(token_clean)
    except ValueError:
        raise UnrecognizedRequirementError(f"Cannot parse count value: '{token}'")


class DesignAgent:
    """Parses natural language engineering requirements into EngineeringSpec objects."""

    def __init__(self) -> None:
        pass

    def parse(self, requirement_text: str) -> EngineeringSpec:
        """Parse requirement text into an EngineeringSpec.

        Args:
            requirement_text: Natural language or structured string specifying design requirements.

        Returns:
            EngineeringSpec: The validated and structured engineering specification.

        Raises:
            UnrecognizedRequirementError: If input does not match a known component pattern
                                          or is missing essential parameters.
        """
        if not requirement_text or not requirement_text.strip():
            raise UnrecognizedRequirementError("Requirement text cannot be empty.")

        text = requirement_text.strip()

        # Check for bracket component pattern
        if self._is_bracket_requirement(text):
            return self._parse_bracket(text)

        # Unrecognized component
        raise UnrecognizedRequirementError(
            f"Could not recognize component pattern in requirement: '{text}'. "
            "Supported components in v0.1: 'bracket'."
        )

    def _is_bracket_requirement(self, text: str) -> bool:
        """Determine if requirement text is describing a bracket."""
        text_lower = text.lower()
        bracket_indicators = [
            "bracket",
            "mounting bracket",
            "l-bracket",
            "angle bracket",
            "flat bracket",
        ]
        return any(indicator in text_lower for indicator in bracket_indicators)

    def _parse_bracket(self, text: str) -> EngineeringSpec:
        """Extract bracket dimensions and hole parameters from text."""
        length: float | None = None
        width: float | None = None
        thickness: float | None = None

        # 1. Try 3-way dimension match (e.g. 100 x 80 x 5 mm)
        match_3way = _DIM_3WAY_PATTERN.search(text)
        if match_3way:
            length = float(match_3way.group("l"))
            width = float(match_3way.group("w"))
            thickness = float(match_3way.group("t"))
        else:
            # 2. Try named dimension matches
            match_l = _LENGTH_NAMED_PATTERN.search(text)
            match_w = _WIDTH_NAMED_PATTERN.search(text)
            match_t = _THICKNESS_NAMED_PATTERN.search(text)

            if match_l and match_w and match_t:
                length = float(match_l.group("val"))
                width = float(match_w.group("val"))
                thickness = float(match_t.group("val"))

        if length is None or width is None or thickness is None:
            raise UnrecognizedRequirementError(
                f"Incomplete bracket dimensions in requirement: '{text}'. "
                "Length, width, and thickness must all be specified (e.g. '100 x 80 x 5 mm')."
            )

        if length <= 0 or width <= 0 or thickness <= 0:
            raise UnrecognizedRequirementError(
                f"Bracket dimensions must be strictly positive. Got length={length}, width={width}, thickness={thickness}."
            )

        # Parse holes
        hole_count: float = 0.0
        hole_diameter: float = 0.0

        if _NO_HOLES_PATTERN.search(text):
            hole_count = 0.0
            hole_diameter = 0.0
        else:
            match_count_diam = _HOLE_COUNT_DIAM_PATTERN.search(text)
            match_count_then_diam = _HOLE_COUNT_THEN_DIAM_PATTERN.search(text)
            match_count_exp = _HOLE_COUNT_EXPLICIT_PATTERN.search(text)
            match_diam_exp = _HOLE_DIAM_EXPLICIT_PATTERN.search(text)

            if match_count_diam:
                hole_count = _parse_count_or_num(match_count_diam.group("count"))
                hole_diameter = float(match_count_diam.group("diam"))
            elif match_count_then_diam:
                hole_count = _parse_count_or_num(match_count_then_diam.group("count"))
                hole_diameter = float(match_count_then_diam.group("diam"))
            elif match_count_exp and match_diam_exp:
                hole_count = _parse_count_or_num(match_count_exp.group("val"))
                hole_diameter = float(match_diam_exp.group("val"))
            elif "hole" in text.lower():
                # Hole mentioned but could not parse count/diameter
                raise UnrecognizedRequirementError(
                    f"Mentioned holes in requirement but could not parse count and diameter: '{text}'"
                )

        if hole_count < 0 or hole_diameter < 0:
            raise UnrecognizedRequirementError("Hole count and diameter must be non-negative.")

        if hole_count > 0 and hole_diameter <= 0:
            raise UnrecognizedRequirementError(
                f"Hole diameter must be strictly positive when hole count is {hole_count}."
            )

        if hole_diameter >= min(length, width):
            raise UnrecognizedRequirementError(
                f"Hole diameter ({hole_diameter} mm) cannot be larger than or equal to bracket dimensions ({length} x {width} mm)."
            )

        parameters: dict[str, float] = {
            "length": length,
            "width": width,
            "thickness": thickness,
            "hole_diameter": hole_diameter,
            "hole_count": hole_count,
        }

        requirements: list[Requirement] = [
            Requirement(name="length", value=length, unit="mm"),
            Requirement(name="width", value=width, unit="mm"),
            Requirement(name="thickness", value=thickness, unit="mm"),
        ]

        constraints: list[Constraint] = [
            Constraint(name="length", operator="==", value=length),
            Constraint(name="width", operator="==", value=width),
            Constraint(name="thickness", operator="==", value=thickness),
        ]

        if hole_count > 0:
            requirements.extend([
                Requirement(name="hole_diameter", value=hole_diameter, unit="mm"),
                Requirement(name="hole_count", value=hole_count, unit=None),
            ])
            constraints.extend([
                Constraint(name="hole_diameter", operator="==", value=hole_diameter),
                Constraint(name="hole_count", operator="==", value=hole_count),
            ])

        metadata: dict[str, Any] = {
            "raw_requirement": text,
            "unit": "mm",
            "parser": "rule_based",
        }

        return EngineeringSpec(
            component="bracket",
            requirements=requirements,
            constraints=constraints,
            objectives=[],
            parameters=parameters,
            metadata=metadata,
        )
