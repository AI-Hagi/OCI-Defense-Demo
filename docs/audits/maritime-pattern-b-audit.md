# Compliance Audit — Recipe L "maritime" (Pattern B)

**Date:** 2026-04-28
**Branch:** `feat/sovdefence-app-swarm`
**Scope:**
- `frontend/src/layers/{types,registry,index,maritime}.ts`
- `frontend/src/views/LagebildView.tsx`
- `frontend/src/types/classification.ts`
- `frontend/src/App.tsx` (added route `/lagebild`)
- `frontend/src/components/Sidebar.tsx` (added nav entry)
- `services/ais-multiplexer/` (new FastAPI WebSocket multiplexer)
- `db/schema/09_vessels_seed.sql`
- `db/queries/maritime-pgql.md`
- `services/ais-multiplexer/.env.example.maritime-additions` (root `.env.example` does not exist in repo — fallback per agent spec)

## ✓ Pass-Items

- **Audit-Tabelle korrekt:** `services/ais-multiplexer/app/audit.py` schreibt ausschließlich `INSERT INTO audit_events` (verifiziert via `grep -rn 'INSERT INTO audit_'`). Kein Treffer für `osint_audit` oder `audit_log`.
- **Vault-Pattern eingehalten:** Kein `os.environ['*KEY*']`-Read im Multiplexer-Code. Alle Secret-Reads laufen über `app.vault.get_secret(ocid)` mit `MOCK_VAULT_KEY`-Fallback nur für Local-Dev (akzeptabel, dokumentiert).
- **Region nicht hardcoded:** Einzige Region-Treffer sind `pydantic-settings` `Field(default="eu-frankfurt-1", alias="OCI_REGION")` (Konvention) sowie Kommentare und `.env.example`-Defaults — keine String-Konstanten in produktivem Code-Pfad.
- **Kein 23ai/23c-Residue:** `grep -rn '23ai\|23c' db/schema/09_vessels_seed.sql services/ais-multiplexer/` → 0 Treffer.
- **Kein IIFE-Pattern (ADR-0001):** `grep -rn 'WV\.layers' frontend/src/layers/` → 0 Treffer. Layer-Modul folgt strikt dem `LayerRegistry`-Pattern.
- **Klassifizierungs-Coverage:** `frontend/src/layers/maritime.ts:124` setzt `_wvClassification: frame.classification ?? 100` an jeder Entity — Default 100 (OPEN) gemäß Recipe-L-Spezifikation.
- **`_wv*`-Konvention:** `_wvType`, `_wvMeta`, `_wvLat`, `_wvLon`, `_wvClassification`, `_wvSources` sind alle gesetzt (`maritime.ts:120–126`).
- **Compartment-Disziplin:** Einzige Compartment-Referenzen in `services/ais-multiplexer/` zeigen auf `oci-defence-demo` (settings.py + .env.example). Kein Bleed nach anderen Compartments.
- **Vault-OCID-Platzhalter:** `services/ais-multiplexer/.env.example` und `services/ais-multiplexer/.env.example.maritime-additions` enthalten beide `VAULT_AIS_STREAM_KEY_OCID` als TODO-Platzhalter. `settings.py` liest die ENV-Variable.
- **Audit-Bypass:** Keine `try: ... except: pass`-Konstruktion um den `audit_events`-Insert. `audit.py` loggt + retried, schluckt Fehler nicht.
- **`any`-Disziplin:** `grep -rn ': any' frontend/src/layers/ frontend/src/views/LagebildView.tsx` → 0 Treffer im neuen TS-Code.
- **TypeScript Build:** `npm run build` (in `frontend/`) durchgelaufen mit Cesium + neuem Layer-Code, 2616 Module, 6.67 s, keine TS-Errors.
- **Python Compile:** `python3 -m py_compile app/*.py` (in `services/ais-multiplexer/`) sauber.

## ✗ Block-Items (must fix before commit)

*Keine.*

## ⚠ Warnings (non-blocking)

- **Root `.env.example` fehlt im Repo.** Da das File nicht existiert, wurde der Vault-Platzhalter nach `services/ais-multiplexer/.env.example.maritime-additions` geschrieben (per Agent-Fallback-Anweisung). **Empfehlung:** beim nächsten Sprint ein zentrales Repo-Root-`.env.example` anlegen und alle Service-spezifischen Templates dort konsolidieren — sonst entsteht Drift zwischen Service-eigenen `.env.example`-Files.
- ~~**Bbox-Default ist mehrfach referenziert.**~~ **RESOLVED 2026-04-28** — die Bbox-Stellen sind drei *konzeptionell verschiedene* Begriffe und wurden entsprechend getrennt: (1) Subscription-Bbox als SSOT in `services/ais-multiplexer/app/settings.py:AIS_BBOX_DEFAULT` mit Override aus repo-root `.env`; (2) Camera-Default in `frontend/src/views/LagebildView.tsx:CAMERA_DEFAULT_BBOX` (umbenannt von `BALTIC_BBOX`, mit explizitem Kommentar dass es nicht der Subscription-Filter ist); (3) Seed-Bbox in `db/schema/09_vessels_seed.sql` (Header-Kommentar wahrheitsgemäß auf 53–60 N, 8–25 E aktualisiert — bewusst weiter als die Live-Subscription, damit Demo-Queries Tallinn-Helsinki abdecken). `services/ais-multiplexer/.env.example` definiert `AIS_BBOX_DEFAULT` nicht mehr lokal, sondern verweist auf das Root-Template.
- **Cesium-Bundle-Größe:** Production-Build liefert `index-*.js` mit 904 KB (gzip 265 KB). Per Vite-Warning >500 KB. Nicht kritisch für die Demo, aber für UC4-Production-Deploy: Code-Splitting via `manualChunks` setzen (Cesium und @cesium/widgets in eigene Chunks).
- **Frontend-Tests sind Mock-heavy.** `frontend/src/layers/__tests__/maritime.test.ts` und `frontend/src/views/__tests__/LagebildView.test.tsx` mocken Cesium komplett. Sie verifizieren das Modul-Kontrakt + Toggle-Existenz, **nicht** das tatsächliche Cesium-Rendering. Ein E2E-Test mit Playwright (bereits als devDep installiert, `frontend/package.json:25`) wäre der nächste Schritt.
- **Tester-Frontend-Output war Lücke.** Der Tester-Agent hat nur Backend-Tests ausgeliefert; Frontend-Tests + smoke-test.sh wurden nachträglich vom Orchestrator ergänzt. Ursache: 5 von 6 Agent-Tool-Returns kamen mit "Tool result missing due to internal error" zurück (Harness-Macke, kein Agent-Fehler). Files wurden trotzdem geschrieben, aber Tester war partiell. **Empfehlung:** Beim nächsten Recipe-Run Tester-Output explizit verifizieren und ggf. Re-Spawn.
- **Cesium-Token:** `import.meta.env.VITE_CESIUM_TOKEN` wird zur Laufzeit gelesen, fehlt aber in der dokumentierten Env-Liste in `services/ais-multiplexer/.env.example` (das ist auch nicht der richtige Ort — Frontend-Tokens gehören nach `frontend/.env.example`, das es im Repo aktuell nicht gibt). **Empfehlung:** `frontend/.env.example` mit `VITE_CESIUM_TOKEN` und `VITE_MARITIME_WS_URL` anlegen.

## Verdict

**PASS_WITH_WARNINGS** — Code-Pfad ist commit-fähig. Keine harten Compliance-Verstöße. Die fünf Warnings sind alle Verbesserungs-Hinweise, kein Blocker.

## Reproducibility

Alle Checks sind als deterministische `grep`-Calls dokumentiert (siehe `.agents/compliance-auditor.md` Prüf-Checkliste). Re-run via:

```bash
cd /home/ubuntu/oci-defense-demo
grep -rn 'INSERT INTO audit_'  services/ais-multiplexer/ db/
grep -rn 'os.environ\[.*KEY' services/ais-multiplexer/
grep -rn 'WV\.layers'         frontend/src/layers/
grep -rn '23ai\|23c'          db/schema/09_vessels_seed.sql services/ais-multiplexer/
```
