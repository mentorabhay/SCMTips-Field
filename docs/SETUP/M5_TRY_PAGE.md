# "Try a look" — the console page for judges (M5-W01)

A judge who has no glasses can see the M5 look from a browser: sign in to the console, open **Try a look** in the
menu (`/try`), pick a test case and a photo, press **Look**. Field runs the same look as the glasses
(SAM 3.1 counts and outlines the items, Muse Spark 1.3 reads the labels, fixed rules check pack size and expiry, the
answer is spoken) on that photo. **Nothing is posted**: no task, no goods receipt, no claim.

## What the page does

1. **The delivery.** C1 grocery delivery (default: expect 8 packs of 6 pieces) or C2 pharmacy receipt (default:
   expect 5 boxes, flag expiry within 90 days). The numbers can be changed.
2. **The photo.** One of the two bundled SAMPLE photos (`apps/field-console/public/samples/`, drawn by
   `uv run python -m tools.samples.try_photos`; synthetic, no brands, logos or faces), or an upload: JPEG or PNG,
   at most 5 MB. The browser scales it to at most 1600 px on its long side and re-encodes it as JPEG (this also drops
   EXIF data such as GPS) before it is sent.
3. **The answer.** The photo as field-api stored it, with numbered outlines (blue while the labels are read, then
   green good / red damaged), the counts, each item's label read, the pack-size and expiry findings and the proposal
   ("Receive 7, flag 1 — SAMPLE: nothing is posted"). The browser speaks the first answer ("8 of 8 packs. Reading the
   labels.") and, when the look turns final (the page polls every second for up to 60 s, as the phone does), the
   rest (`say_next`). **Speak again** repeats it. A browser without speech synthesis shows the text only.
4. **Rules mode.** When no model answers (cloud AI off, no key, a budget cap reached, the price not confirmed, a
   time-out) the look answers in rules mode and the page says why in plain words, e.g. "today's budget for try looks
   is used up". This is exactly what the glasses do without AI.

## Guard rails (enforced by field-api, not by the page)

| Rule | Setting | Answer |
|---|---|---|
| Who | permission `field.try.use`: field.operator, field.supervisor, field.viewer | 403 otherwise |
| Photo type | JPEG or PNG, checked on the file's bytes | 415 `FIELD-TRY-415-TYPE` |
| Photo size | at most 5 MB | 413 `FIELD-TRY-413-SIZE` |
| Rate | `FIELD_TRY_LOOKS_PER_HOUR` (default 10) per person per rolling hour | 429 `FIELD-TRY-429-RATE` + `Retry-After` |
| Spend | `AI_TRY_DAILY_CAP_USD` (default 3) per tenant per UTC day, inside `AI_DAILY_CAP_USD` and `AI_BUDGET_META_USD` | rules mode, reason `AI_TRY_DAILY_CAP` |
| Faces | found and pixelated by field-api before the photo is stored and before any model call | `image.faces_blurred` |
| Retention | photo and label text kept 24 h, then deleted by field-worker (every 10 min) | photo 410 after 24 h |

Face detection is OpenCV's Haar cascades (in the `opencv-python-headless` wheel), on the photo as stored. It misses
small, strongly turned or partly covered faces, so the page asks people not to photograph anyone. On the 2-vCPU build
sandbox it took about 2.5-5 s for a 1600 x 1200 photo, before the SAM call.

## Hosting

- field-api and field-worker both need `FIELD_TRY_PHOTO_DIR` on the same volume (the image sets
  `/data/try-photos`); the worker deletes expired photos there.
- Optional: `AI_TRY_DAILY_CAP_USD` (default 3), `FIELD_TRY_LOOKS_PER_HOUR` (default 10).
- Migration `field_0067_m5_try` (`stack migrate` / `alembic upgrade head`).
- Judges need a sign-in whose role maps to field.operator, field.supervisor or field.viewer.

## Try it locally

```
uv run python -m tools.dev_stack.stack up        # field-api, worker, console
# console: http://127.0.0.1:3000/try  (development sign-in as Supervisor)
```

Without `MODEL_API_KEY` and `AI_CLOUD_ENABLED=true` the page shows rules mode. With the dev stack's model stand-in
(`stack up --model-standin`) the stand-in answers the scene it was last given, not the photo: it is a test double,
not a model. What SAM 3.1 and Muse Spark answer on the SAMPLE photos is UNVERIFIED until the hosted stack runs them
with the real key (docs/META_FIELD.md rows 20, 23).
