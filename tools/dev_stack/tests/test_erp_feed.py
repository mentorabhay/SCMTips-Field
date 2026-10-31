"""`stack smoke --erp-feed` (tools/dev_stack/erp_feed.py, M4 Q10): the pieces that need no running core.

The smoke itself runs against the stand-in or the real core (FIELD_CORE_TARGET); here: how the core's on-hand is read
(its latest count per item and location), how the core is compared with erp-sim, and that the smoke flag routes to it.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from tools.dev_stack import erp_feed, stack


def test_m4_c15_the_cores_on_hand_is_its_latest_count_per_item_and_location() -> None:
    rows: list[dict[str, Any]] = [{"item_code": "CP-204", "location_code": "PLANT-GOA", "as_of": "2026-10-19", "on_hand_qty": "1680.0000"},
            {"item_code": "CP-204", "location_code": "PLANT-GOA", "as_of": "2026-11-01", "on_hand_qty": "1680"},
            {"item_code": "CP-204", "location_code": "PLANT-GOA", "as_of": "2026-10-31", "on_hand_qty": "3280"},
            {"item_code": "FG-100", "location_code": "DC-MIL", "as_of": "2026-10-19", "on_hand_qty": 140}]
    assert erp_feed._latest_on_hand(rows) == {("CP-204", "PLANT-GOA"): 1680.0, ("FG-100", "DC-MIL"): 140.0}


def test_m4_c15_compare_names_each_difference_and_ignores_what_only_the_core_holds() -> None:
    stock = {("CP-204", "PLANT-GOA"): 1680.0, ("RM-307", "PLANT-GOA"): 2600.0}
    pos = {("PO-26-1002", "CP-204"): {"kind": "PO", "ref": "PO-26-1002", "item_code": "CP-204", "qty": 1600,
                                      "location_code": "PLANT-GOA", "due_date": "2026-11-20", "status": "open"}}
    core_pos = {("PO-26-1002", "CP-204"): {"qty": "1600.0000", "status": "open", "due_date": "2026-11-20",
                                           "location_code": "PLANT-GOA"},
                ("WO-26-2001", "FG-100"): {"qty": "240", "status": "released", "due_date": "2026-11-06"}}
    same = erp_feed.compare(stock, pos, {**stock, ("FG-100", "DC-MIL"): 1.0}, core_pos)
    assert same == []
    diff = erp_feed.compare(stock, pos, {("CP-204", "PLANT-GOA"): 3280.0},
                            {("PO-26-1002", "CP-204"): {**core_pos[("PO-26-1002", "CP-204")], "status": "received"}})
    assert diff == ["on-hand CP-204@PLANT-GOA: erp-sim 1680, core 3280.0", "on-hand RM-307@PLANT-GOA: erp-sim 2600, core None",
                    "PO PO-26-1002 CP-204: erp-sim (Decimal('1600'), 'open', '2026-11-20', 'PLANT-GOA'), core"
                    " (Decimal('1600.0000'), 'received', '2026-11-20', 'PLANT-GOA')"]


def test_m4_c15_smoke_erp_feed_routes_to_the_erp_feed_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(stack, "load_env", lambda: {})
    monkeypatch.setattr(stack, "apply_ports", lambda: None)

    def fake(a: argparse.Namespace, api: str) -> int:
        called.append(api)
        return 0

    monkeypatch.setattr(stack, "smoke_erp_feed_cmd", fake)
    args = argparse.Namespace(api="http://field", wait=1.0, erp_feed=True, core=False, approver=False, home=False,
                              all=False)
    assert stack.cmd_smoke(args) == 0
    assert called == ["http://field"]
