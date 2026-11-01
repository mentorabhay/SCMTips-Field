"""Settings of the vision look, read from the environment per call (so a restart with a new .env.local applies).

Per-stage deadlines (seconds; each clamped to 0.5..6, the model client's own per-call cap):
  VISION_INSTANCES_DEADLINE_S  default 4.0   SAM 3.1 instances
  VISION_LABELS_DEADLINE_S     default 6.0   Muse Spark label + damage reads, all batches together
  VISION_FALLBACK_DEADLINE_S   default 4.0   the Baseten (Llama 3.2 Vision) fallback for label reads
Other settings:
  VISION_EXPIRY_WINDOW_DAYS    default 90    a site's "expiring soon" window when the line names none (C2)
  VISION_CROPS_PER_CALL        default 8     instance crops sent in one Muse call (1..20; the API takes up to 50)
  VISION_MAX_INSTANCES         default 40    instances kept from one look (largest scores first)
  VISION_MIN_SCORE             default 0.3   SAM instances below this confidence are dropped
  VISION_INSTANCES_MODEL       default sam-3.1
  VISION_LABELS_MODEL          default ASSISTANT_MODEL, else muse-spark-1.3
  VISION_BASETEN_MODEL_ID      default BASETEN_MODEL_ID (the Llama 3.2 Vision deployment); needs BASETEN_BASE_URL
  META_MODEL_API_BASE_URL      default https://api.meta.ai/v1 (the dev stack points it at its local model stand-in)
"""

from __future__ import annotations

import math
import os

INSTANCES_MODEL = "sam-3.1"
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
    return _float("VISION_INSTANCES_DEADLINE_S", 4.0, 0.5, 6.0)


def labels_deadline_s() -> float:
    return _float("VISION_LABELS_DEADLINE_S", 6.0, 0.5, 6.0)


def fallback_deadline_s() -> float:
    return _float("VISION_FALLBACK_DEADLINE_S", 4.0, 0.5, 6.0)


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
