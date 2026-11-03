"""Ports of the vision look: what a model stage gives the orchestrator, independent of the provider's wire format.

Production adapters: ``vision.sam.Sam31Instances`` (SAM 3.1 on the Meta Model API Responses endpoint) and
``vision.labels.ChatLabelReader`` (Muse Spark 1.3 image input on chat completions; the same class over Baseten for
the Llama 3.2 Vision fallback). Their request and response shapes are UNVERIFIED until the owner's Gate 0 run
(docs/META_FIELD.md rows 20 and 23): tests drive the adapters through an httpx test transport in test code only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels of the original capture (x1, y1 exclusive)


@dataclass(frozen=True)
class FoundInstance:
    box: Box
    score: float | None
    polygon: list[list[int]] | None = None


@dataclass(frozen=True)
class LabelRead:
    """What a model read on one instance. ``read`` is false when no label value was legible (never guessed)."""

    read: bool
    pieces_per_unit: int | None = None
    batch: str | None = None
    expiry: str | None = None  # "YYYY-MM" or "YYYY-MM-DD"
    damaged: bool = False
    damage_note: str | None = None
    raw: str | None = None  # printed text the model used; kept 30 days, never logged


@dataclass
class ModelCall:
    """One model call of a look, as the response's ``models`` lists it."""

    model: str
    purpose: str  # 'instances' | 'labels'
    latency_ms: int
    cost_usd: Decimal
    outcome: str  # 'ok' or an error code (AI_TIMEOUT, AI_PRICE_UNCONFIRMED, ...)
    provider: str = "meta"


@dataclass
class CallContext:
    tenant_id: str | None
    request_id: str | None
    calls: list[ModelCall] = field(default_factory=list)


class InstanceFinder(Protocol):
    """Instances of ``prompt`` (an object noun) in a JPEG; raises assistant.model.ModelError when no answer."""

    @property
    def model(self) -> str: ...

    def find(self, image_jpeg: bytes, width: int, height: int, prompt: str, *, timeout_s: float,
             ctx: CallContext) -> list[FoundInstance]: ...


class LabelReader(Protocol):
    """Label and damage reads for numbered crops; raises assistant.model.ModelError when no answer."""

    @property
    def model(self) -> str: ...

    def read(self, crops: Sequence[tuple[int, bytes]], *, case: str, object_noun: str, timeout_s: float,
             ctx: CallContext) -> dict[int, LabelRead]: ...


@dataclass(frozen=True)
class Naming:
    """What layer 1 (vision.namer) saw: up to three prompt words, best first, and the estimated count (or None)."""

    nouns: tuple[str, ...]
    estimate: int | None


class ObjectNamer(Protocol):
    """Names the goods in a JPEG and estimates their count; raises assistant.model.ModelError when no answer."""

    @property
    def model(self) -> str: ...

    def name(self, image_jpeg: bytes, *, timeout_s: float, ctx: CallContext) -> Naming: ...


@dataclass(frozen=True)
class VisionPorts:
    """The adapters one look uses: instances, then label readers in order (primary, fallback), and the namer of the
    instances stage's layer 1 (M5-V11; None: SAM's own words only)."""

    instances: InstanceFinder | None
    readers: tuple[LabelReader, ...] = ()
    namer: ObjectNamer | None = None
