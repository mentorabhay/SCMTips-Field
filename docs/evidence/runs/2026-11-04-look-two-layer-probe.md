# Look two-layer probe and live check (3-4 Nov 2026, IST)

Why the look changed to two layers (M5-V11), and the proof that the hosted look counts real packs after the change.
All calls were made from the hosted field-api container (scm-vm-1, asia-south1) with its own key and budget guard.

## The problem

The owner's hosted looks on 3 Nov 2026 (23:53, 23:55, 23:58 IST) photographed **5 real biscuit packs** with the
phone camera (720 x 1600 after the app's scaling, faces blurred on the phone). Every look answered
**"0 of 20 packs"**: SAM 3.1 returned no boxes for the case's noun `pack` or its fallback `box`
(`vision_look.reasons = ["instances:retry:box"]`, 2 SAM calls each, ~5 s). The stored photos were checked by eye:
upright, sharp, all five packs large on a plain towel.

## SAM 3.1 word probe (one stored photo, 720 x 1600)

| Word | Found | Confidence |
|---|---|---|
| pack | 0 | |
| box | 0 | |
| bag | 0 | |
| packet | 5 | 0.82-0.86 |
| biscuit packet | 5 | 0.64-0.67 |
| snack | 5 | 0.87-0.91 |
| food package | 5 | 0.78-0.81 |
| package | **5** | 0.92-0.96 |
| yellow packet | 5 | 0.94-0.97 |

A 3:4 crop and a 3:4 grey-padded copy gave the same picture: the photo's shape was not the cause.

Control, the try page's SAMPLE photo (1280 x 960, 8 packs): `box` found 8 at only 0.59-0.60 and 0 when the photo
was rotated 90 degrees or halved; `pack` 0; `packet` 0; `snack` 0; `package` **8** at 0.88; `yellow packet` 8 at 0.88.

## Two-layer probe (Muse Spark 1.3 names the goods, reasoning low, photo at 768 px)

| Photo | Muse said | Muse's noun to SAM | `package` to SAM | Wall time |
|---|---|---|---|---|
| owner 23:53 | packet, about 5 | 5 | 5 | 8.4 s |
| owner 23:55 | packet, about 5 | 5 | 5 | 9.1 s |
| owner 23:58 | packet, about 5 | 5 | 5 | 9.4 s |
| SAMPLE | packet, about 8 | **0** | 8 | 8.5 s |

Muse's count estimate was exact every time; its own word was not always one SAM answers to. Hence the design in
`vision/service.py` (`find_instances`): SAM on the case's noun and Muse naming in parallel; an empty or disagreeing
answer makes SAM try `package`, `box` and the named nouns; the answer nearest the estimate is kept.

## Live check after the deploy (release scm-9a147e1-724797e-20261104-0130, 4 Nov ~01:40 IST)

The deployed `find_instances` with the production ports (`VISION_NAMING=true`, deadline 10 s), noun `pack`:

| Photo | Seen | Time | Reasons |
|---|---|---|---|
| owner 23:53 | **5** | 5.7 s | retry:package,box · named:package~5 · prompt:package |
| owner 23:55 | **5** | 4.7 s | retry:package,box · named:package~5 · prompt:package |
| owner 23:58 | **5** | 5.8 s | retry:package,box · named:package~5 · prompt:package |
| SAMPLE | **8** | 6.5 s | retry:package,box · named:package~8 · prompt:package |

Calls per look: 3 SAM 3.1 images and 1 Muse naming call (4.4-6.4 s). Hosted case defaults in the same release:
grocery 8 packs of 6 pieces, pharmacy 5 boxes (D-4).
