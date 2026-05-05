# GEOINT Demo-Imagery — Setup & Verwendung

Zwei Skripte zum Befüllen der GEOINT-View mit echten Bildern für die
BMVg/Bundeswehr-Demo. Erzeugt 10 Bilder gemischt aus EU-souveränen
Sentinel-2-Aufnahmen (5×) und frei lizenzierten Aerial-/UAV-Bildern (5×).

## Voraussetzungen

Auf der Dev-Workstation (`ubuntu@dev-workstation`):

- OCI CLI Profil `DEFENCE_DEMO` funktional
- Repo-Root `.env` mit den drei Sentinel-Vault-OCIDs:
  - `VAULT_SENTINEL_CLIENT_ID_OCID`
  - `VAULT_SENTINEL_CLIENT_SECRET_OCID`
  - `VAULT_SENTINEL_INSTANCE_ID_OCID`
- Sentinel-Hub Configuration mit Layer `TRUE-COLOR-HIGHLIGHT-OPTIMIZED`
  (das hattest du schon — Instance-ID `5ae1c1e5-...`)
- Tools: `bash`, `curl`, `jq`, `python3`, `oci` CLI

## Installation

```bash
cd ~/oci-defense-demo
mkdir -p scripts/demo-imagery
# Lade die zwei .sh-Dateien aus diesem Bundle nach scripts/demo-imagery/
chmod +x scripts/demo-imagery/*.sh
```

## Ausführung

```bash
cd ~/oci-defense-demo/scripts/demo-imagery

# 1. Sentinel-2-Bilder (5×, dauert ~1-3 Minuten)
bash fetch-sentinel-imagery.sh

# 2. UAV-/Aerial-Bilder (5×, dauert ~30 Sekunden)
bash fetch-uav-imagery.sh
```

Nach erfolgreicher Ausführung liegen 10 Bilder in `./demo-images/`.

## Demo-Talking-Points pro Bild

### Sentinel-2 (Sovereignty-Story)

Beim Upload Header `X-Platform-Kind: satellite` setzen.

| Bild | Story |
|---|---|
| **bornholm** | "Insel Bornholm — Konsistenz mit unserer Maritime-Lagebild-Bbox. Sie sehen die gleiche Region in der wir gerade die AIS-Schiffsbewegungen tracken." |
| **eckernfoerde** | "Bundeswehr-Marinestützpunkt Eckernförde aus unserer kuratierten NATO-Hafendatenbank. Aufnahme Sentinel-2 L2A, EU-Copernicus-Programm, vollständig souverän." |
| **wilhelmshaven** | "Größter deutscher Marinehafen. Demonstriert die Auflösungsgrenze von Sentinel-2 (10m/Pixel) — geeignet für Strukturen, nicht für Einzelobjekte." |
| **suwalki-gap** | "Suwałki-Gap, polnisch-litauischer Grenzkorridor. Strategischer Anker zwischen Kaliningrad und Belarus. Sentinel-Coverage hier ist zentral für EU-Sicherheitslage." |
| **kaliningrad-approach** | "Kaliningrad/Pillau, Hafeneinfahrt. NATO-Kontext — wir können die Region beobachten, ohne auf US-kommerzielle Datenquellen angewiesen zu sein." |

**Ehrliche Erwartung:** Sentinel-2 hat 10m Auflösung. YOLOv8 nano (COCO-trainiert) wird auf diesen Bildern wenige Detections produzieren — vielleicht ein einzelnes Schiff in Wilhelmshaven, sonst wenig. Das ist eine **physikalische Auflösungs-Grenze**, kein Modell-Schwäche. Demo-Story dazu: "Sentinel-2 ist unsere souveräne Datenquelle für strategische Übersicht. Für Einzelobjekt-Erkennung kombinieren wir das mit höher aufgelösten UAV-Aufnahmen — wie diese hier..." → wechseln zu UAV-Bildern.

### UAV/Aerial (Detection-Story)

Beim Upload Header `X-Platform-Kind: uav` setzen.

| Bild | Story | Erwartete Detections |
|---|---|---|
| **uav-hamburg-port** | "Hamburger Hafen, Container-Terminal — typisches Bild eines maritimen Logistikknotens." | 5-15 boats, 2-5 trucks |
| **uav-frankfurt-airport** | "Frankfurt Airport, Vorfeld. YOLO erkennt Luftfahrzeuge auch bei dichter Anordnung." | 3-8 airplanes, 5-20 vehicles |
| **uav-stadtgebiet** | "Hamburg Stadtgebiet — urbanes Lagebild." | 20-50 cars, einige trucks |
| **uav-autobahn** | "Autobahnkreuz Maschen — Verkehrsfluss-Analyse." | 15-30 cars, 5-15 trucks |
| **uav-industrieanlage** | "BASF Ludwigshafen — Industrieanlage, kritische Infrastruktur." | 3-8 trucks, einzelne cars |

## Demo-Flow-Vorschlag

**5 Minuten BMVg-Demo:**

1. **Sentinel-Bornholm hochladen** (X-Platform-Kind: satellite)
   - "Souveräne EU-Aufklärung, Auflösung 10m, geeignet für Strukturen"
   - Detection-Output: 0-2 (ehrlich kommunizieren)
   
2. **UAV-Frankfurt-Airport hochladen** (X-Platform-Kind: uav)
   - "Drohnenaufnahme, höhere Auflösung, taktisches Lagebild"
   - Detection-Output: 5-15 — sichtbares Resultat
   
3. **Auf der Karte zeigen:** beide Scenes als Polygone, mit Detection-Counts in den Popups
   
4. **Übergang zu UC4 Lagebild:** "die Sentinel-Aufnahme deckt genau den Bereich ab, wo unsere AIS-Layer aktive Schiffsbewegungen zeigen"

## Troubleshooting

**Sentinel-Skript scheitert mit "Token length: 0":**
- OAuth-Credentials nicht geladen. Prüfe: `cat .env | grep VAULT_SENTINEL`
- Token-Endpoint nicht erreichbar. Test: `curl -I https://identity.dataspace.copernicus.eu/`

**Sentinel-Skript scheitert mit "HTTP 400":**
- Bbox falsches Format oder Layer nicht in deiner Configuration
- Manueller Test: GetCapabilities-Call wie damals beim Pre-Flight

**Sentinel-Bilder sind komplett schwarz oder weiß:**
- Wolkenbedeckung der gefundenen Aufnahme zu hoch
- `MAX_CLOUD=10` setzen (statt 30) und nochmal laufen lassen
- Oder Zeitfenster ausweiten: `TIME_FROM=2026-01-01T00:00:00Z`

**UAV-Skript: einzelne Bilder scheitern:**
- Wikimedia rate-limited dann gelegentlich. Skript einfach nochmal laufen lassen — bereits geladene Bilder werden übersprungen.

**Frontend-Upload klappt aber 500 vom Backend:**
- Bild-Format vom Backend nicht akzeptiert (PIL kann's nicht decoden)
- JPEG vorziehen vor PNG bei großen Sentinel-Bildern
- Console-Log vom geoint-Pod: `kubectl -n sovdefence logs deployment/geoint --tail=50`
