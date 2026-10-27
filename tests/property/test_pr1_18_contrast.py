"""Property Test PR1.18: WCAG AA Color Contrast Verification (TC1.163).

Computes W3C relative luminance and asserts contrast ratio >= 4.5:1 for standard text
across all declared token pairs in light, dark and lens modes.
"""

import json
from pathlib import Path

import pytest

TOKENS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "packages"
    / "ui-tokens"
    / "tokens"
    / "color.json"
)


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    hex_clean = hex_str.lstrip("#")
    return int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16)


def srgb_channel_to_linear(c_255: int) -> float:
    c = c_255 / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_str: str) -> float:
    r, g, b = hex_to_rgb(hex_str)
    r_lin = srgb_channel_to_linear(r)
    g_lin = srgb_channel_to_linear(g)
    b_lin = srgb_channel_to_linear(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = relative_luminance(hex1)
    l2 = relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.property
def test_ui_tokens_contrast_ratios():
    assert TOKENS_PATH.exists()
    colors = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))["color"]

    # Light Mode pairs
    light_pairs = [
        ("light text on bg", colors["light"]["text"]["value"], colors["light"]["bg"]["value"]),
        (
            "light text on surface",
            colors["light"]["text"]["value"],
            colors["light"]["surface"]["value"],
        ),
        (
            "light textMuted on bg",
            colors["light"]["textMuted"]["value"],
            colors["light"]["bg"]["value"],
        ),
        (
            "light primaryText on primary",
            colors["light"]["primaryText"]["value"],
            colors["light"]["primary"]["value"],
        ),
    ]

    for name, fg, bg in light_pairs:
        ratio = contrast_ratio(fg, bg)
        assert ratio >= 4.5, (
            f"Contrast ratio for {name} ({ratio:.2f}:1) failed WCAG AA 4.5:1 threshold (fg={fg}, bg={bg})"
        )

    # Dark Mode pairs
    dark_pairs = [
        ("dark text on bg", colors["dark"]["text"]["value"], colors["dark"]["bg"]["value"]),
        (
            "dark text on surface",
            colors["dark"]["text"]["value"],
            colors["dark"]["surface"]["value"],
        ),
        (
            "dark textMuted on bg",
            colors["dark"]["textMuted"]["value"],
            colors["dark"]["bg"]["value"],
        ),
    ]

    for name, fg, bg in dark_pairs:
        ratio = contrast_ratio(fg, bg)
        assert ratio >= 4.5, (
            f"Contrast ratio for {name} ({ratio:.2f}:1) failed WCAG AA 4.5:1 threshold (fg={fg}, bg={bg})"
        )

    # Lens HUD Monochrome pairs (Requires extreme high contrast for outdoor sunlight visibility)
    lens_pairs = [
        ("lens text on bg", colors["lens"]["text"]["value"], colors["lens"]["bg"]["value"]),
        ("lens accent on bg", colors["lens"]["accent"]["value"], colors["lens"]["bg"]["value"]),
    ]

    for name, fg, bg in lens_pairs:
        ratio = contrast_ratio(fg, bg)
        assert ratio >= 7.0, (
            f"Contrast ratio for HUD {name} ({ratio:.2f}:1) failed sunlight visibility threshold >= 7:1"
        )
