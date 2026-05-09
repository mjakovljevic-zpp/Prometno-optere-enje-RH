"""08 - Dohvat OSM trase autocesta (samo postojece, bez rampa i konstrukcije).

Preuzima sve highway=motorway way-eve za Hrvatsku, iskljucuje motorway_link
(rampe), construction (gradnja) i proposed (planirano).

Izlaz: data/intermediate/osm_motorway.geojson
"""
from __future__ import annotations
import json
import urllib.request
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"
INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Samo highway=motorway (ne motorway_link, ne construction)
QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="HR"]->.hr;
(
  way["highway"="motorway"](area.hr);
);
out body geom;
"""


def fetch_overpass():
    print("[08] Saljem upit na Overpass API (motorway, samo postojece)...", flush=True)
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data,
                                 headers={"User-Agent": "karta-opterecenja/1.0"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    out = fetch_overpass()
    elements = out.get("elements", [])
    print(f"[08] Dobio {len(elements)} way-eva", flush=True)

    features = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {}) or {}
        # OSM 'ref' za motorway moze biti 'A1', 'A1;A2' itd.
        ref = tags.get("ref", "")
        if not ref:
            continue
        # Geometrija je niz lon/lat tocaka
        coords = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(coords) < 2:
            continue
        # Iz 'A1;A2' uzmi prvu oznaku (cesta moze biti dijeljena)
        primary = ref.split(";")[0].strip()
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "id": el["id"],
                "ref": primary,
                "ref_all": ref,
                "name": tags.get("name"),
                "lanes": tags.get("lanes"),
                "maxspeed": tags.get("maxspeed"),
                "oneway": tags.get("oneway"),
            },
        })

    fc = {"type": "FeatureCollection", "features": features}
    out_path = INTERMEDIATE_DIR / "osm_motorway.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"[08] Spremljeno {len(features)} segmenata", flush=True)

    # Sazetak po cesti
    by_road = {}
    for f in features:
        r = f["properties"]["ref"]
        by_road[r] = by_road.get(r, 0) + 1
    print("[08] Po cesti:", dict(sorted(by_road.items())), flush=True)
    print("[08] OK", flush=True)


if __name__ == "__main__":
    main()
