"""Functional Location Mask Validator (Task T4.003 / FR4.008 / TC4.105).

Parses, validates, and extracts hierarchy metadata from SAP Functional Location codes
according to configurable mask patterns (e.g., IN01-TWR-nnnn[-Tnn[-Sx[-Lnn[-Pnn]]]]).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

DEFAULT_MASK = os.environ.get("FIELD_FL_MASK", "IN01-TWR-nnnn[-Tnn[-Sx[-Lnn[-Pnn]]]]")

# Regex segment definitions
RE_SITE = re.compile(r"^[A-Z0-9]{2,6}-TWR-\d{4}$")
RE_TOWER = re.compile(r"^T\d{2}$")
RE_SECTOR = re.compile(r"^S[A-D]$")
RE_LEVEL = re.compile(r"^L\d{2}$")
RE_POSITION = re.compile(r"^P\d{2}$")
RE_SHELTER = re.compile(r"^SH(?:\d{2})?$")
RE_RACK = re.compile(r"^R\d{2}$")
RE_RACK_SLOT = re.compile(r"^(?:S|SL)\d{2}$")


@dataclass
class FlValidationResult:
    is_valid: bool
    code: str
    kind: str | None = None
    parent_code: str | None = None
    short_code: str | None = None
    site_code: str | None = None
    sector_code: str | None = None
    level_num: int | None = None
    depth: int = 1
    error_segment: str | None = None
    error_reason: str | None = None


def validate_fl_code(code: str, mask: str | None = None) -> FlValidationResult:
    """Validate a functional location code and derive kind, parent, and attributes.

    Returns FlValidationResult with is_valid=True on success, or is_valid=False with
    error_segment and error_reason identifying the invalid segment.
    """
    if not code or not isinstance(code, str):
        return FlValidationResult(
            is_valid=False,
            code=code or "",
            error_segment=None,
            error_reason="Code cannot be empty",
        )

    code = code.strip()
    segments = code.split("-")

    # Minimum segments for a site: prefix (e.g. IN01), type (TWR), number (0042)
    # Total segments for site = 3 (IN01-TWR-0042)
    if len(segments) < 3:
        return FlValidationResult(
            is_valid=False,
            code=code,
            error_segment=segments[0] if segments else None,
            error_reason="Incomplete site prefix, expected FORMAT: [COUNTRY][REGION]-TWR-nnnn",
        )

    site_part = f"{segments[0]}-{segments[1]}-{segments[2]}"
    if not RE_SITE.match(site_part):
        return FlValidationResult(
            is_valid=False,
            code=code,
            error_segment=site_part,
            error_reason=f"Invalid site prefix '{site_part}', must match format XXnn-TWR-nnnn",
        )

    # Base level: Site itself
    if len(segments) == 3:
        return FlValidationResult(
            is_valid=True,
            code=code,
            kind="tower_site",
            parent_code=None,
            short_code=segments[2],
            site_code=site_part,
            depth=1,
        )

    # Sub-elements
    remaining = segments[3:]

    # Check if branch is Shelter or Tower
    first_sub = remaining[0]
    if RE_SHELTER.match(first_sub):
        # Shelter branch
        shelter_code = f"{site_part}-{first_sub}"
        if len(remaining) == 1:
            return FlValidationResult(
                is_valid=True,
                code=code,
                kind="shelter",
                parent_code=site_part,
                short_code=first_sub,
                site_code=site_part,
                depth=2,
            )

        # Rack
        second_sub = remaining[1]
        if not RE_RACK.match(second_sub):
            return FlValidationResult(
                is_valid=False,
                code=code,
                error_segment=second_sub,
                error_reason=f"Expected rack segment Rnn, found '{second_sub}'",
            )

        rack_code = f"{shelter_code}-{second_sub}"
        if len(remaining) == 2:
            return FlValidationResult(
                is_valid=True,
                code=code,
                kind="rack",
                parent_code=shelter_code,
                short_code=second_sub,
                site_code=site_part,
                depth=3,
            )

        # Rack Slot
        third_sub = remaining[2]
        if not RE_RACK_SLOT.match(third_sub) and not RE_POSITION.match(third_sub):
            return FlValidationResult(
                is_valid=False,
                code=code,
                error_segment=third_sub,
                error_reason=f"Expected slot segment Snn or Pnn, found '{third_sub}'",
            )

        if len(remaining) == 3:
            return FlValidationResult(
                is_valid=True,
                code=code,
                kind="rack_slot",
                parent_code=rack_code,
                short_code=third_sub,
                site_code=site_part,
                depth=4,
            )

        return FlValidationResult(
            is_valid=False,
            code=code,
            error_segment=remaining[3],
            error_reason=f"Unexpected segment beyond rack slot: '{remaining[3]}'",
        )

    elif RE_TOWER.match(first_sub):
        # Tower branch
        tower_code = f"{site_part}-{first_sub}"
        if len(remaining) == 1:
            return FlValidationResult(
                is_valid=True,
                code=code,
                kind="tower",
                parent_code=site_part,
                short_code=first_sub,
                site_code=site_part,
                depth=2,
            )

        # Sector
        second_sub = remaining[1]
        if not RE_SECTOR.match(second_sub):
            return FlValidationResult(
                is_valid=False,
                code=code,
                error_segment=second_sub,
                error_reason=f"Expected sector segment Sx (A-D), found '{second_sub}'",
            )

        sector_char = second_sub[1]
        sector_fl = f"{tower_code}-{second_sub}"
        if len(remaining) == 2:
            return FlValidationResult(
                is_valid=True,
                code=code,
                kind="sector",
                parent_code=tower_code,
                short_code=second_sub,
                site_code=site_part,
                sector_code=sector_char,
                depth=3,
            )

        # Level
        third_sub = remaining[2]
        if not RE_LEVEL.match(third_sub):
            return FlValidationResult(
                is_valid=False,
                code=code,
                error_segment=third_sub,
                error_reason=f"Expected level segment Lnn, found '{third_sub}'",
            )

        level_num = int(third_sub[1:])
        level_fl = f"{sector_fl}-{third_sub}"
        if len(remaining) == 3:
            return FlValidationResult(
                is_valid=True,
                code=code,
                kind="level",
                parent_code=sector_fl,
                short_code=third_sub,
                site_code=site_part,
                sector_code=sector_char,
                level_num=level_num,
                depth=4,
            )

        # Position
        fourth_sub = remaining[3]
        if not RE_POSITION.match(fourth_sub):
            return FlValidationResult(
                is_valid=False,
                code=code,
                error_segment=fourth_sub,
                error_reason=f"Expected position segment Pnn, found '{fourth_sub}'",
            )

        if len(remaining) == 4:
            return FlValidationResult(
                is_valid=True,
                code=code,
                kind="position",
                parent_code=level_fl,
                short_code=fourth_sub,
                site_code=site_part,
                sector_code=sector_char,
                level_num=level_num,
                depth=5,
            )

        return FlValidationResult(
            is_valid=False,
            code=code,
            error_segment=remaining[4],
            error_reason=f"Unexpected segment beyond position: '{remaining[4]}'",
        )

    else:
        return FlValidationResult(
            is_valid=False,
            code=code,
            error_segment=first_sub,
            error_reason=f"Expected tower (Tnn) or shelter (SH), found '{first_sub}'",
        )
