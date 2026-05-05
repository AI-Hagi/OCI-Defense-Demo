#!/usr/bin/env bash
# fetch-uav-imagery-v2.sh
#
# Lädt 5+ frei lizenzierte Aerial-Bilder. Strategie diesmal:
#  1. Wikimedia API befragt eine Kategorie-Seite und liefert eine Liste
#     existierender Files. Keine geratenen URLs mehr.
#  2. Aus der Liste werden die ersten Files mit Mindestgröße gepickt.
#  3. Resolved jedes File via Wikimedia ImageInfo-API zu seiner
#     direkten upload.wikimedia.org-URL.
#
# Vorteil gegenüber v1: keine 404, weil wir die existierenden Files
# direkt aus dem Wiki-Katalog ziehen.
#
# Output: ./demo-images/uav-*.jpg (5+ Bilder)
#
# Verwendung:
#   bash fetch-uav-imagery-v2.sh

set -euo pipefail

OUT_DIR="${OUT_DIR:-./demo-images}"
mkdir -p "$OUT_DIR"

USER_AGENT="SovDefenceDemo/1.0 (https://cloudebility.com; markus@cloudebility.com)"

# Kategorien aus denen wir Bilder ziehen — alle existieren live, verifiziert
# via Wikimedia-Suche. Format: kategorie|prefix|min_size_bytes|max_count
CATEGORIES=(
  "Category:Aerial_photographs_of_the_Port_of_Hamburg|hamburg-port|2000000|2"
  "Category:Aerial_photographs_of_airports_in_Germany|airport|1500000|2"
  "Category:Aerial_photographs_of_Frankfurt|frankfurt|1500000|1"
)

echo "Fetching aerial images via Wikimedia Commons API"
echo ""

total_downloaded=0

for entry in "${CATEGORIES[@]}"; do
  IFS='|' read -r category prefix min_size max_count <<< "$entry"
  
  echo "  Category: $category"
  echo "  Target: up to $max_count images, min size ${min_size} bytes"
  
  # Schritt 1: Liste der Files in der Kategorie holen
  list_url="https://commons.wikimedia.org/w/api.php?action=query&list=categorymembers&cmtitle=${category}&cmtype=file&cmlimit=20&format=json"
  
  list_response=$(curl -sf -A "$USER_AGENT" "$list_url" 2>&1) || {
    echo "    ERROR: failed to query Wikimedia API for $category"
    echo "    Response: $list_response"
    continue
  }
  
  # Parse: extrahiere Filenames
  file_titles=$(echo "$list_response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for m in d.get('query', {}).get('categorymembers', []):
        title = m.get('title', '')
        if title.startswith('File:') and any(title.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
            print(title)
except Exception as e:
    print(f'PARSE_ERROR: {e}', file=sys.stderr)
")
  
  if [[ -z "$file_titles" ]]; then
    echo "    No image files found in category"
    continue
  fi
  
  count=0
  while IFS= read -r title; do
    [[ -z "$title" ]] && continue
    [[ $count -ge $max_count ]] && break
    
    # Schritt 2: Direkte URL via ImageInfo-API holen
    info_url="https://commons.wikimedia.org/w/api.php?action=query&titles=${title// /_}&prop=imageinfo&iiprop=url|size|mime&format=json"
    
    info_response=$(curl -sf -A "$USER_AGENT" "$info_url" 2>&1) || {
      echo "    skip: imageinfo query failed for $title"
      continue
    }
    
    parsed=$(echo "$info_response" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    pages = d.get('query', {}).get('pages', {})
    for pid, p in pages.items():
        ii = p.get('imageinfo', [])
        if ii:
            print(f\"{ii[0].get('url','')}|{ii[0].get('size',0)}|{ii[0].get('mime','')}\")
            break
except Exception:
    pass
")
    
    [[ -z "$parsed" ]] && continue
    
    IFS='|' read -r url size mime <<< "$parsed"
    
    # Mindestgröße prüfen
    if [[ "$size" -lt "$min_size" ]]; then
      echo "    skip: ${title} too small ($size bytes < $min_size)"
      continue
    fi
    
    # Filename ohne "File:" prefix, lowercase, sicher für Filesystem
    safe_name=$(echo "$title" | sed 's|^File:||' | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9.-' '-' | sed 's/--*/-/g')
    out_file="$OUT_DIR/uav-${prefix}-${count}-${safe_name}"
    
    # Endung normalisieren auf .jpg
    out_file="${out_file%.png}.jpg"
    out_file="${out_file%.jpeg}.jpg"
    [[ "$out_file" != *.jpg ]] && out_file="${out_file}.jpg"
    
    echo "    -> ${out_file##*/}"
    echo "       url:  ${url}"
    echo "       size: $size bytes ($mime)"
    
    if curl -sLf -A "$USER_AGENT" -o "$out_file" "$url"; then
      actual_size=$(stat -c%s "$out_file" 2>/dev/null || stat -f%z "$out_file")
      echo "       OK ($actual_size bytes saved)"
      count=$((count + 1))
      total_downloaded=$((total_downloaded + 1))
    else
      echo "       FAILED to download"
      rm -f "$out_file"
    fi
    
    # Rate-limit gegen Wikimedia
    sleep 1
  done <<< "$file_titles"
  
  echo ""
done

echo ""
echo "Total downloaded: $total_downloaded image(s)"
echo "Files in $OUT_DIR:"
ls -lh "$OUT_DIR"/uav-*.jpg 2>/dev/null | head -20 || echo "  (no files)"

cat << 'TIPS'

---------------------------------------------------------------------
Demo-Tipps:

1. Beim Upload in der GEOINT-View Header X-Platform-Kind: uav setzen.

2. Erwartete YOLOv8n-Performance:
   - Hafen-Bilder:    5-15 boats, einige trucks
   - Flughafen:       3-8 airplanes, Vehicles
   - Stadtgebiete:    20+ cars, einige trucks

3. Falls einzelne Bilder zu klein sind oder keine erkennbaren Objekte
   zeigen: Skript nochmal laufen lassen, Wikimedia liefert dann
   andere Files aus den Kategorien.

4. Bei Wikimedia-Rate-Limit (selten, aber möglich): 5 Minuten warten
   und nochmal.

TIPS
