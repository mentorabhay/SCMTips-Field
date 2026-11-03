"""Settings of the vision look, read from the environment per call (so a restart with a new .env.local applies).

Per-stage deadlines (seconds; each clamped to 0.5..VISION_CALL_CAP_S = 60). Raised after the owner's Gate 0 from India
(1 Nov 2026, docs/evidence/2026-11-01-m5-gate0-093109.txt): SAM 3.1 answered a 1600 px photo in about 5 s, a Muse
Spark image read did not answer within 7.7 s. A look is a deliberate step, so it may take tens of seconds; the app says
it is looking. The assistant's own 6 s cap is unchanged.
  VISION_INSTANCES_DEADLINE_S  default 15    SAM 3.1 instances
  VISION_LABELS_DEADLINE_S     default 30    Muse Spark label + damage reads, all batches together
  VISION_FALLBACK_DEADLINE_S   default 15    the Baseten (Llama 3.2 Vision) fallback for label reads
Muse label reads (reasoning tokens count against max_tokens, dev.meta.ai/docs/reasoning; Gate 0 1 Nov 2026):
  VISION_LABELS_REASONING_EFFORT  default low    Meta's reasoning_effort for label reads (minimal|low|medium|high|xhigh|max)
  VISION_LABELS_MAX_TOKENS        default 4096   base output allowance per call (+512 per crop), 1024..16384
  VISION_LABELS_MAX_TOKENS_CAP    default 12288  the most one label call may use, 2048..16384
Two-layer instances (M5-V11, after the hosted looks of 3-4 Nov 2026; see vision.service SAM_GENERIC):
  VISION_NAMING                default true  Muse Spark names the goods and estimates the count, in parallel with SAM
                                             (false: SAM's own words only, "package" and "box" after the case's noun)
  VISION_NAMING_DEADLINE_S     default 10    the naming call (inside VISION_INSTANCES_DEADLINE_S; ~5.5 s from India)
Other settings:
  VISION_EXPIRY_WINDOW_DAYS    default 90    a site's "expiring soon" window when the line names none (C2)
  VISION_CROPS_PER_CALL        default 8     instance crops sent in one Muse call (1..20; the API takes up to 50)
  VISION_MAX_INSTANCES         default 40    instances kept from one look (largest scores first)
  VISION_MIN_SCORE             default 0.3   SAM instances below this confidence are dropped
  VISION_INSTANCES_MODEL       default sam-3.1
  VISION_LABELS_MODEL          default ASSISTANT_MODEL, else muse-spark-1.3
  VISION_BASETEN_MODEL_ID      default BASETEN_MODEL_ID (the Llama 3.2 Vision deployment); needs BASETEN_BASE_URL
  VISION_LABEL_MIN_INSTANCE_PX default 200   labels left unread while the instances' median short side is smaller
                                             than this (pixels of the capture): reason labels:close_look_needed
  META_MODEL_API_BASE_URL      default https://api.meta.ai/v1 (the dev stack points it at its local model stand-in)
"""

from __future__ import annotations

import math
import os

INSTANCES_MODEL = "sam-3.1"
VISION_CALL_CAP_S = 60.0  # the longest single vision model call (the assistant keeps its own 6 s cap)
LABELS_MODEL = "muse-spark-1.3"


def _float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, "").strip())
    except ValueError:
        return default
    if not math.isfinite(v):
        return default
    return max(lo, min(hi, v))


def _int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw.lstrip("-").isdigit():
        return default
    return max(lo, min(hi, int(raw)))


def instances_deadline_s() -> float:
    return _float("VISION_INSTANCES_DEADLINE_S", 15.0, 0.5, VISION_CALL_CAP_S)


def labels_deadline_s() -> float:
    return _float("VISION_LABELS_DEADLINE_S", 30.0, 0.5, VISION_CALL_CAP_S)


def fallback_deadline_s() -> float:
    return _float("VISION_FALLBACK_DEADLINE_S", 15.0, 0.5, VISION_CALL_CAP_S)


def expiry_window_days() -> int:
    return _int("VISION_EXPIRY_WINDOW_DAYS", 90, 0, 3650)


def crops_per_call() -> int:
    return _int("VISION_CROPS_PER_CALL", 8, 1, 20)


def max_instances() -> int:
    return _int("VISION_MAX_INSTANCES", 40, 1, 200)


def min_score() -> float:
    return _float("VISION_MIN_SCORE", 0.3, 0.0, 1.0)


def instances_model() -> str:
    return os.getenv("VISION_INSTANCES_MODEL", "").strip() or INSTANCES_MODEL


def labels_model() -> str:
    return os.getenv("VISION_LABELS_MODEL", "").strip() or os.getenv("ASSISTANT_MODEL", "").strip() or LABELS_MODEL


def meta_base_url() -> str:
    return os.getenv("META_MODEL_API_BASE_URL", "").strip() or "https://api.meta.ai/v1"


def baseten_vision_model() -> str:
    return os.getenv("VISION_BASETEN_MODEL_ID", "").strip() or os.getenv("BASETEN_MODEL_ID", "").strip()


def baseten_base_url() -> str:
    return os.getenv("BASETEN_BASE_URL", "").strip()


def label_min_instance_px() -> int:
    return _int("VISION_LABEL_MIN_INSTANCE_PX", 200, 8, 5000)


REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")  # "none" is refused by Muse Spark (HTTP 400)


def naming_enabled() -> bool:
    """M5-V11: layer 1 of the instances stage (Muse names the goods and estimates the count); off only by false/0/no."""
    return os.getenv("VISION_NAMING", "").strip().lower() not in ("false", "0", "no", "off")


def naming_deadline_s() -> float:
    return _float("VISION_NAMING_DEADLINE_S", 10.0, 0.5, VISION_CALL_CAP_S)


def labels_reasoning_effort() -> str:
    v = os.getenv("VISION_LABELS_REASONING_EFFORT", "").strip().lower()
    return v if v in REASONING_EFFORTS else "low"


def labels_max_tokens_base() -> int:
    return _int("VISION_LABELS_MAX_TOKENS", 4096, 1024, 16384)


def labels_max_tokens_cap() -> int:
    return _int("VISION_LABELS_MAX_TOKENS_CAP", 12288, 2048, 16384)
