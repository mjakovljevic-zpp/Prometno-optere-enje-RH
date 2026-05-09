"""07 - Dohvat motorway_junction čvorova iz OSM-a (Overpass API).

Za sve hrvatske autoceste (A1-A11) preuzima sve motorway_junction
nodove s atributima 'name' i 'ref' koji pomažu povezati ih s
'čv. <ime>' iz brojačke tablice.

Izlaz: data/intermediate/osm_junctions.geojson
"""
from __future__ import annotations
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"
INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:120];
area["ISO3166-1"="HR"]->.hr;
(
  node["highway"="motorway_junction"](area.hr);
);
out body;
"""


def fetch_overpass():
    print("[07] Saljem upit na Overpass API (motorway_junction)...", flush=True)
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data,
                                 headers={"User-Agent": "karta-opterecenja/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    out = fetch_overpass()
    elements = out.get("elements", [])
    print(f"[07] Dobio {len(elements)} cvorova", flush=True)

    features = []
    for el in elements:
        if el.get("type") != "node":
            continue
        tags = el.get("tags", {}) or {}
        name = tags.get("name") or tags.get("name:hr")
        ref = tags.get("ref")
        if not (name or ref):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
            "properties": {
                "id": el["id"],
                "name": name,
                "ref": ref,
                "ref_road": tags.get("ref:road") or tags.get("highway:ref"),
                "destination": tags.get("destination"),
                "junction_ref": tags.get("junction:ref"),
            },
        })

    fc = {"type": "FeatureCollection", "features": features}
    out_path = INTERMEDIATE_DIR / "osm_junctions.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    print(f"[07] Spremljeno {len(features)} cvorova u {out_path}", flush=True)
    print("[07] OK", flush=True)


if __name__ == "__main__":
    main()
