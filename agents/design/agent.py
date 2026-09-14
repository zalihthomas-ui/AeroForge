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
    """Raised when an engineering requirement cannot be parsed or component is unsupported."""

    pass


class IncompleteRequirementError(UnrecognizedRequirementError):
    """Raised when a component is recognized but required parameters are missing."""

    def __init__(
        self,
        component: str,
        missing: list[str],
        provided: dict[str, float],
        message: str | None = None,
    ) -> None:
        self.component = component
        self.missing = missing
        self.provided = provided
        if message is None:
            message = (
                f"Incomplete {component} requirement: missing parameter(s) {missing}. "
                f"Provided: {provided}"
            )
        super().__init__(message)


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

# Regex patterns for bracket dimensions
_DIM_3WAY_PATTERN = re.compile(
    r"(?P<l>\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:[xX*×\u00d7]|\bby\b)\s*"
    r"(?P<w>\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:[xX*×\u00d7]|\bby\b)\s*"
    r"(?P<t>\d+(?:\.\d+)?)\s*(?:mm)?",
    re.IGNORECASE,
)

_DIM_2WAY_PATTERN = re.compile(
    r"(?P<l>\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:[xX*×\u00d7]|\bby\b)\s*"
    r"(?P<w>\d+(?:\.\d+)?)\s*(?:mm)?",
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

# Regex patterns for bracket holes
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

# Regex patterns for wing parameters
_WING_SPAN_PATTERN = re.compile(
    r"\b(?:wing[_\s]*span|wingspan|span)\s*[:=]?\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.IGNORECASE,
)
_ROOT_CHORD_PATTERN = re.compile(
    r"\b(?:root[_\s]*chord|root)\s*[:=]?\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.IGNORECASE,
)
_TIP_CHORD_PATTERN = re.compile(
    r"\b(?:tip[_\s]*chord|tip)\s*[:=]?\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?:mm)?\b",
    re.IGNORECASE,
)
_SWEEP_PATTERN = re.compile(
    r"\b(?:leading[_\s-]*edge[_\s]*sweep|sweep[_\s]*angle|le[_\s]*sweep|sweep)\s*[:=]?\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?:deg|degrees|°)?\b",
    re.IGNORECASE,
)
_DIHEDRAL_PATTERN = re.compile(
    r"\b(?:dihedral[_\s]*angle|dihedral)\s*[:=]?\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?:deg|degrees|°)?\b",
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
            IncompleteRequirementError: If a component is recognized but required parameters are missing.
            UnrecognizedRequirementError: If input does not match a known component pattern
                                          or has invalid parameter values.
        """
        if not requirement_text or not requirement_text.strip():
            raise UnrecognizedRequirementError("Requirement text cannot be empty.")

        text = requirement_text.strip()

        # Check for bracket component pattern
        if self._is_bracket_requirement(text):
            return self._parse_bracket(text)

        # Check for wing component pattern
        if self._is_wing_requirement(text):
            return self._parse_wing(text)

        # Unrecognized component
        raise UnrecognizedRequirementError(
            f"Could not recognize component pattern in requirement: '{text}'. "
            "Supported components in v0.3: 'bracket', 'wing'."
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

    def _is_wing_requirement(self, text: str) -> bool:
        """Determine if requirement text is describing a wing."""
        text_lower = text.lower()
        wing_indicators = [
            "wing",
            "uav wing",
            "aircraft wing",
            "aerodynamic wing",
        ]
        return any(indicator in text_lower for indicator in wing_indicators)

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
            # 2. Try 2-way dimension match (e.g. 100 x 80 mm)
            match_2way = _DIM_2WAY_PATTERN.search(text)
            if match_2way:
                length = float(match_2way.group("l"))
                width = float(match_2way.group("w"))

            # 3. Try named dimension matches
            if length is None:
                match_l = _LENGTH_NAMED_PATTERN.search(text)
                if match_l:
                    length = float(match_l.group("val"))

            if width is None:
                match_w = _WIDTH_NAMED_PATTERN.search(text)
                if match_w:
                    width = float(match_w.group("val"))

            if thickness is None:
                match_t = _THICKNESS_NAMED_PATTERN.search(text)
                if match_t:
                    thickness = float(match_t.group("val"))

        provided: dict[str, float] = {}
        missing: list[str] = []

        if length is not None:
            provided["length"] = length
        else:
            missing.append("length")

        if width is not None:
            provided["width"] = width
        else:
            missing.append("width")

        if thickness is not None:
            provided["thickness"] = thickness
        else:
            missing.append("thickness")

        if missing:
            raise IncompleteRequirementError(
                component="bracket",
                missing=missing,
                provided=provided,
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

    def _parse_wing(self, text: str) -> EngineeringSpec:
        """Extract wing parameters from text."""
        match_span = _WING_SPAN_PATTERN.search(text)
        match_root = _ROOT_CHORD_PATTERN.search(text)
        match_tip = _TIP_CHORD_PATTERN.search(text)
        match_sweep = _SWEEP_PATTERN.search(text)
        match_dihedral = _DIHEDRAL_PATTERN.search(text)

        provided: dict[str, float] = {}
        missing: list[str] = []

        if match_span:
            provided["wing_span"] = float(match_span.group("val"))
        else:
            missing.append("wing_span")

        if match_root:
            provided["root_chord"] = float(match_root.group("val"))
        else:
            missing.append("root_chord")

        if match_tip:
            provided["tip_chord"] = float(match_tip.group("val"))
        else:
            missing.append("tip_chord")

        if match_sweep:
            provided["sweep"] = float(match_sweep.group("val"))
        else:
            missing.append("sweep")

        if match_dihedral:
            provided["dihedral"] = float(match_dihedral.group("val"))
        else:
            missing.append("dihedral")

        if missing:
            raise IncompleteRequirementError(
                component="wing",
                missing=missing,
                provided=provided,
            )

        wing_span = provided["wing_span"]
        root_chord = provided["root_chord"]
        tip_chord = provided["tip_chord"]
        sweep = provided["sweep"]
        dihedral = provided["dihedral"]

        if wing_span <= 0 or root_chord <= 0 or tip_chord <= 0:
            raise UnrecognizedRequirementError(
                f"Wing dimensions must be strictly positive. Got wing_span={wing_span}, "
                f"root_chord={root_chord}, tip_chord={tip_chord}."
            )

        if sweep < -45.0 or sweep > 45.0:
            raise UnrecognizedRequirementError(
                f"Wing sweep angle must be within [-45, 45] degrees. Got sweep={sweep}."
            )

        if dihedral < -45.0 or dihedral > 45.0:
            raise UnrecognizedRequirementError(
                f"Wing dihedral angle must be within [-45, 45] degrees. Got dihedral={dihedral}."
            )

        parameters: dict[str, float] = {
            "wing_span": wing_span,
            "root_chord": root_chord,
            "tip_chord": tip_chord,
            "sweep": sweep,
            "dihedral": dihedral,
        }

        requirements: list[Requirement] = [
            Requirement(name="wing_span", value=wing_span, unit="mm"),
            Requirement(name="root_chord", value=root_chord, unit="mm"),
            Requirement(name="tip_chord", value=tip_chord, unit="mm"),
            Requirement(name="sweep", value=sweep, unit="deg"),
            Requirement(name="dihedral", value=dihedral, unit="deg"),
        ]

        constraints: list[Constraint] = [
            Constraint(name="wing_span", operator="==", value=wing_span),
            Constraint(name="root_chord", operator="==", value=root_chord),
            Constraint(name="tip_chord", operator="==", value=tip_chord),
            Constraint(name="sweep", operator="==", value=sweep),
            Constraint(name="dihedral", operator="==", value=dihedral),
        ]

        metadata: dict[str, Any] = {
            "raw_requirement": text,
            "unit": "mm",
            "angle_unit": "deg",
            "parser": "rule_based",
        }

        return EngineeringSpec(
            component="wing",
            requirements=requirements,
            constraints=constraints,
            objectives=[],
            parameters=parameters,
            metadata=metadata,
        )
