# GEOINT Default-View Fix — 2026-05-01

**Branch:** `feat/sovdefence-app-swarm`
**Scope:** Frontend only — `frontend/src/views/GeointView.tsx` and its test file.
**Demo audience:** BMVg / Bundeswehr — Map muss von Anfang an Mitteleuropa zeigen.

## Problem (vorher)

GeointView landed users on a Russland-zoomed Leaflet view because:

- The `MapContainer` already had `center=DEFAULT_CENTER` and
  `zoom=DEFAULT_ZOOM` (commit `6a3b503`), but the test contract for that
  pair was implicit — only a `<div data-testid="leaflet-map">` was
  asserted, not the geographic coordinates the component passes through.
- All 16 existing scenes in the database had `footprint = null` (a known
  pre-fix legacy from before commit `a12b228`'s footprint persistence).
  The previous hint banner reading `"X Szenen ohne Geolokalisation. UAV-
  Aufnahmen ohne EXIF-GPS-Daten benötigen manuelle Verortung beim
  Upload."` was strictly diagnostic and ate vertical space without
  pointing the operator at the workaround.
- The hint banner had no dismiss affordance, so an operator who
  accepted the message had to live with it for the rest of the
  session.

## Fix (nachher)

### `GeointView.tsx`

- Default-View: `MapContainer` continues to use `DEFAULT_CENTER =
  [51.0, 10.0]` (Mitte Deutschland) and `DEFAULT_ZOOM = 5`. **Behaviour
  unchanged from commit `6a3b503`** — the change is in the test
  contract that locks this in (see below).
- Banner-Text:
  > Hochgeladene Szenen werden mit synthetischen Footprints versehen.
  > Für präzise Lagebild-Korrelation: 'Position wählen'-Feature nutzen
  > (siehe Roadmap UC1.B).
- Banner-Verhalten: only renders when `scenes.length > 0 AND
  scenes.every(s => !s.footprint)` AND the operator hasn't dismissed
  it this session.
- Dismiss-Button: 14px X icon (`lucide-react`) with `aria-label="Hinweis
  schließen"` and `data-testid="geoint-footprint-hint-dismiss"`.
  Persistence via `sessionStorage` key
  `sov:geoint:footprint-hint-dismissed`. Tab refresh re-shows; reload
  within the same session keeps it hidden.

### `__tests__/GeointView.test.tsx`

- `MapContainer` mock now surfaces `center` / `zoom` props as
  `data-center` (JSON-stringified `LatLngTuple`) and `data-zoom`
  (string) data-attributes, enabling assertion without a live Leaflet
  instance.
- New test: `defaults the leaflet map to Mitteleuropa (51.0°N, 10.0°E)
  at zoom 5` — locks the BMVg / Bundeswehr default view contract.
- New test: `does NOT render hint banner when scenes list is empty` —
  empty list ≠ all-missing-footprints, so banner stays hidden.
- New test: `hides the hint banner once the operator clicks the
  dismiss button` — covers the dismiss button + sessionStorage write.
- Updated existing test: `renders hint banner when all scenes lack
  footprint` — assertions now match the new banner wording (`/synthetischen
  Footprints/`, `/Position w[aä]hlen/`, `/Roadmap UC1\.B/`) and the
  dismiss button's accessible name.
- Existing test kept verbatim: `does NOT render hint banner when at
  least one scene has a footprint` — same condition, no behaviour
  change.

## Test status

```
$ npx vitest run src/views/__tests__/GeointView.test.tsx
 Test Files  1 passed (1)
      Tests  9 passed (9)

$ npx vitest run        # full frontend suite
 Test Files  24 passed (24)
      Tests  142 passed (142)
```

No pre-existing test was rewritten. The two banner tests were updated
to match the new contract (text + dismiss button), which falls under
"the test directly tests the changed behaviour" — not a forbidden
rewrite of an unrelated test.

## Stop-Kriterien

| Stop reason | Hit? |
|---|---|
| Map library is something other than Leaflet | No — confirmed `react-leaflet` |
| Pre-existing tests broke | No — 142/142 pass; only banner tests were updated to match the new banner contract |

## Roadmap-Link

The banner now points the operator at the upcoming **UC1.B 'Position
wählen'** feature — manual footprint selection at upload time for
operators working with images that lack EXIF GPS but for whom the
synthetic-Mitteleuropa fallback (commit `a12b228`) is too imprecise.
That feature is not in this commit; the banner is the user-facing
breadcrumb pointing to it.
