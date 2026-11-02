"""The walk through the app, as data: what to tap, what to wait for, which screens to keep (M5-K01)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    kind: str
    """shot | tap | maybe | wait | back | sleep | advance | type (tap the field `arg`, type `name`) | hidekb"""
    arg: str = ""
    name: str = ""
    required: bool = False
    """A required step that fails stops the walk (nothing after it can be reached)."""


# Buttons that move the first run forward without choosing anything (glasses and permissions are optional).
ADVANCE = r"^(Allow and continue|Continue without a test photo|Skip|Not now|Continue|Next)$"

# A SAMPLE address, typed only to show the password step (no password is ever typed).
SAMPLE_EMAIL = "judge01@sample-drone-oem.example"

WALK: tuple[Step, ...] = (
    Step("sleep", "6"),
    Step("shot", name="welcome-look"),
    Step("maybe", r"^Next$"),
    Step("shot", name="welcome-hear"),
    Step("maybe", r"^Next$"),
    Step("shot", name="welcome-confirm"),
    Step("tap", r"^Get started$", required=True),
    Step("sleep", "2"),
    Step("shot", name="sign-in-ways"),
    Step("tap", r"^Continue with e-mail$"),
    Step("sleep", "1"),
    Step("hidekb"),
    Step("shot", name="sign-in-e-mail"),
    Step("type", r"^Work e-mail$", name=SAMPLE_EMAIL),
    Step("hidekb"),
    Step("maybe", r"^Use my password$"),
    Step("hidekb"),
    Step("shot", name="sign-in-password"),
    Step("tap", r"^Back$"),
    Step("wait", r"^Try the SAMPLE demo$"),
    Step("maybe", r"^Scan a code from your computer$"),
    Step("sleep", "2"),
    Step("shot", name="sign-in-scan-code"),
    Step("tap", r"^Back$"),
    Step("wait", r"^Try the SAMPLE demo$"),
    Step("maybe", r"^I have an invite$"),
    Step("sleep", "1"),
    Step("hidekb"),
    Step("shot", name="sign-in-invite"),
    Step("tap", r"^Back$"),
    Step("wait", r"^Try the SAMPLE demo$"),
    Step("maybe", r"^Create an account$"),
    Step("sleep", "1"),
    Step("shot", name="create-account"),
    Step("maybe", r"^(Close|Back)$"),
    Step("wait", r"^Try the SAMPLE demo$"),
    Step("tap", r"^Try the SAMPLE demo$", required=True),
    Step("sleep", "6"),
    Step("shot", name="after-demo-sign-in"),
    Step("advance", r"Where are you working\?", name="setup"),
    Step("shot", name="site-pick"),
    Step("tap", r"Sandbox|Home \(sandbox\)"),
    Step("sleep", "4"),
    Step("advance", r"Working as", name="to-home"),
    Step("shot", name="home-warehouse"),
    Step("tap", r"^Working as"),
    Step("sleep", "1"),
    Step("shot", name="role-switcher"),
    Step("maybe", r"^Approvals"),
    Step("sleep", "3"),
    Step("shot", name="home-approvals"),
    Step("tap", r"^Working as"),
    Step("maybe", r"^Scan product|^Scan$"),
    Step("sleep", "3"),
    Step("shot", name="home-scan"),
    Step("tap", r"^Working as"),
    Step("maybe", r"^Tower"),
    Step("sleep", "3"),
    Step("shot", name="home-tower"),
    Step("tap", r"^Working as"),
    Step("maybe", r"^Warehouse"),
    Step("sleep", "3"),
    Step("maybe", r"^Start work$"),
    Step("sleep", "3"),
    Step("shot", name="work-session"),
    Step("maybe", r"New grocery delivery"),
    Step("sleep", "3"),
    Step("shot", name="grocery-step-1-look"),
    Step("back"),
    Step("maybe", r"New pharmacy delivery"),
    Step("sleep", "3"),
    Step("shot", name="pharmacy-step-1-look"),
    Step("back"),
    Step("maybe", r"^Inbox"),
    Step("sleep", "3"),
    Step("shot", name="inbox"),
    Step("maybe", r"Decision waiting|^Decisions|Hear the decision|Listen to the brief"),
    Step("sleep", "3"),
    Step("shot", name="decision"),
    Step("back"),
    Step("maybe", r"^Scan$"),
    Step("sleep", "3"),
    Step("shot", name="scan-tab"),
    Step("maybe", r"^Check a box$"),
    Step("sleep", "3"),
    Step("shot", name="box-check-start"),
    Step("back"),
    Step("maybe", r"^Profile$|^Me$"),
    Step("sleep", "2"),
    Step("shot", name="profile"),
    Step("maybe", r"^Settings$"),
    Step("sleep", "2"),
    Step("shot", name="settings"),
    Step("maybe", r"^Connections$"),
    Step("sleep", "2"),
    Step("shot", name="connections"),
    Step("back"),
    Step("maybe", r"^Diagnostics$"),
    Step("sleep", "2"),
    Step("shot", name="diagnostics"),
    Step("back"),
    Step("maybe", r"^Glasses"),
    Step("sleep", "2"),
    Step("shot", name="glasses"),
)
