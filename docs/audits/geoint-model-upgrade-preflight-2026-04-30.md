# GEOINT YOLOv8 Model Upgrade — Pre-flight License Report (STOPPED)

**Date:** 2026-04-30
**Branch:** `feat/sovdefence-app-swarm`
**Outcome:** **STOPPED at the license-clarity gate.** No code, Dockerfile,
manifests, tests, or images touched. The spec mandates: *"WENN nur
akademische / non-commercial Lizenzen: STOPPEN und melden mit konkreten
Lizenz-Quotes. Markus entscheidet dann wie wir vorgehen."*

This file is the pre-flight evidence package for that decision.

## Pre-flight 1 — Asset availability

Both target weight files **are available** as Ultralytics-distributed
public artefacts (Azure-Blob-CDN-backed, 302-redirect from the GitHub
release URL):

```
$ curl -sIL "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-obb.pt" | grep -E "HTTP|content-length"
HTTP/2 302
content-length: 0
HTTP/2 200
content-length: 6567590             # 6.6 MB

$ curl -sIL "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-obb.pt" | grep -E "HTTP|content-length"
HTTP/2 302
content-length: 0
HTTP/2 200
content-length: 23267238            # 23.3 MB
```

Both assets resolve, both Azure-Blob-served, both pullable from the OKE
virtual node (same CDN as the existing yolov8n.pt fetch).

**Verdict: assets are reachable.** No technical blocker on this axis.

## Pre-flight 2 — Ultralytics code license (model framework)

The `ultralytics` Python package containing the `YOLO()` loader is
licensed under **GNU AGPL-3.0**. Source quote from the upstream
LICENSE file:

```
$ curl -s https://raw.githubusercontent.com/ultralytics/ultralytics/main/LICENSE | head -2
                    GNU AFFERO GENERAL PUBLIC LICENSE
                       Version 3, 19 November 2007
```

Implication: AGPL-3.0 is a copyleft network-aware license. Hosting an
AGPL-3.0 service over a network (which is exactly what `services/
geoint/` does — FastAPI + ultralytics over HTTP behind an OCI LB) means
**either** open-sourcing the entire `services/geoint` codebase under
AGPL-3.0 **or** purchasing an Ultralytics Enterprise License.

Markus has flagged this as an out-of-scope question:
> "Markus muss das später separat regeln, aber technisch verfügbar."

**Status:** known concern, not a hard blocker for the technical
upgrade itself. The same AGPL-3.0 obligation already applies to the
existing yolov8n.pt deployment — switching weights doesn't change the
risk surface here.

## Pre-flight 3 — DOTA dataset license (training data) — **HARD BLOCKER**

The yolov8n-obb.pt and yolov8s-obb.pt weights are *trained on the
DOTA dataset* (per the official Ultralytics docs at
`https://docs.ultralytics.com/datasets/obb/dota-v2/`). DOTA's official
terms of use:

> Source: <https://captain-whu.github.io/DOTA/dataset.html>, exact
> verbatim from the rendered HTML —
>
> > **Image Source and Usage License**
> >
> > […]
> >
> > Use of the Google Earth images must respect the "Google Earth"
> > terms of use.
> >
> > **All images and their associated annotations in DOTA
> > can be used for academic purposes only, but any commercial use
> > is prohibited.**

Confirmed via `curl -sL`:
```html
<strong style="color:red">can be used for academic purposes only,
but any commercial use is prohibited</strong>.
```

The bold red rendering and the "but any commercial use is prohibited"
clause are unambiguous. The same restriction applies verbatim across
DOTA-v1.0, v1.5, and v2.0 (one shared license section on the dataset
page).

### Why this propagates to the trained weights

A YOLOv8 model trained on DOTA images + annotations is a **derivative
work** of the dataset. Standard ML-license analysis (and the
prevailing position in IP/AI law as of 2024-2026) treats the trained
weights as carrying the data-source restrictions, *especially* when
the data license explicitly forbids commercial use. The Ultralytics
release notes acknowledge DOTA as the training source for the OBB
weights without disclaiming the inherited restriction.

The Sovereign Defence Intelligence Platform is positioned as a
**commercial defence-industry product** (per `CLAUDE.md`: "EU-Variante
als souveränes Daten-, KI- und Compliance-Backbone … inspiriert von
Oracles DICE 2026"). Demos to NATO / Bundeswehr / industry tenants
are commercial-use scenarios under any reasonable reading.

### Conclusion

**Using `yolov8n-obb.pt` or `yolov8s-obb.pt` in this codebase as it
is intended to be deployed (commercial defence product) violates the
DOTA non-commercial restriction.** This is the exact scenario the
spec told me to halt on.

## Pre-flight 4 — Quick survey of permissively-licensed alternatives

For Markus's decision, here is a non-exhaustive survey of common
satellite/aerial detection datasets and their commercial-use status:

| Dataset / weights | Domain | License posture (best public source) | Commercial ok? |
|---|---|---|---|
| **DOTA v1/v1.5/v2 (basis of yolov8-obb.pt)** | Aerial 15-class OBB | "academic purposes only, but any commercial use is prohibited" | **No** |
| **xView (DARPA / DIUx)** | Satellite 60-class | CC BY-NC-SA 4.0 + US-DoD restrictions; per spec already flagged | **No** |
| **VisDrone (Tianjin Univ.)** | UAV 10-class | Site doesn't publish a license file — academic conf. data, ambiguous | Unclear → treat as no |
| **NWPU VHR-10** | Satellite 10-class | "for research purposes only" per dataset page | **No** |
| **iSAID** | Aerial instance-seg 15-class | "for research only" | **No** |
| **DIOR / DIOR-R** | Satellite 20-class OBB | Academic, no commercial clause | Unclear → treat as no |
| **RarePlanes (CosmiQ Works)** | Satellite plane detection | CC BY-SA 4.0 | **Yes** (with attribution + share-alike) |
| **SpaceNet challenges** | Satellite buildings/roads | CC BY-SA 4.0 (most challenges) | **Yes** (with attribution + share-alike) |
| **OpenAerialMap + OpenStreetMap** | Aerial / labels | ODbL 1.0 (data) + permissive imagery | **Yes** |

The two clearly commercial-OK options (RarePlanes, SpaceNet) cover
**single-class / building-segment** problems, **not** the 15-class
multi-object OBB story we'd want for a defence demo. There is — to
the best of this 30-minute survey — **no off-the-shelf permissively-
licensed multi-class aerial OBB checkpoint** that maps cleanly onto
the DOTA class taxonomy (plane / ship / harbor / vehicle /
helicopter / …).

This is a known gap in the open ML ecosystem for defence imagery and
is exactly why the demo currently uses generic COCO weights.

## Recommendation paths for Markus

Three concrete options, ordered by risk:

**A. Stay on `yolov8n.pt` (status quo) and lower the IoU/confidence
   threshold to surface more candidate detections on Sentinel/UAV
   tiles.** Zero license risk, zero new code beyond a parameter
   tweak. Detections will still be COCO classes (truck, boat, person,
   …) which the demo audience can interpret; counts go up, the map
   gets visibly populated. The spec calls this an anti-pattern only
   if done *without consultation* — bringing it to Markus is the
   sanctioned route.

**B. Commission a fine-tune on a permissively-licensed dataset
   subset** — e.g. RarePlanes for plane detection, plus a small
   curated harbour set from OpenAerialMap. ~1 GPU-day of training.
   Out of scope for this iteration per the spec ("GPU-basiertes
   eigenes Training in dem Lauf — das ist Multi-Hour + GPU-Bedarf,
   nicht im Scope") but the right long-term answer.

**C. Negotiate a written commercial-use exception with DOTA's
   maintainers (Wuhan University)** before deploying the OBB weights.
   Possible but slow; doesn't help the demo timeline.

A **wrong** option that I refused to take autonomously:
- **D. Deploy the OBB weights anyway with a verbal "we'll regularise
  later" rationalisation.** Compliance-wise this is the same risk
  category as deploying unlicensed proprietary code. The spec's
  anti-pattern list explicitly forbids it.

## What I did NOT touch

- `services/geoint/Dockerfile` — unchanged.
- `services/geoint/app/ml.py` — unchanged.
- `services/geoint/app/routers/scenes.py` — unchanged.
- No new tests written.
- No image built or pushed.
- No commits beyond this status report (and only if Markus approves
  the report itself).

## Reproducibility

```bash
curl -sIL "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-obb.pt" | head -3
curl -sIL "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-obb.pt" | head -3
curl -s https://raw.githubusercontent.com/ultralytics/ultralytics/main/LICENSE | head -2
curl -sL "https://captain-whu.github.io/DOTA/dataset.html" | grep -A1 "academic purposes"
```

---

**Awaiting decision from Markus before any further action.**
