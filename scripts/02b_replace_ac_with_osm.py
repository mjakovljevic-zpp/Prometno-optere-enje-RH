"""02b - Zamijeni AC segmente u mrezi s OSM motorway geometrijom.

Ucitava network_segments.parquet (iz skripte 02), za AC kategoriju
zamjenjuje GPKG segmente OSM motorway segmentima (samo trasa, bez rampa).
Dijelovi koji su u GPKG-u oznaceni kao 'planirano/u izgradnji' implicitno
se ispustaju jer ih OSM ne sadrzi kao motorway.
"""
from __future__ import annotations
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"

CRS_HR = 3765
CRS_WGS84 = 4326


def main():
    print("[02b] Ucitavam mrezu", flush=True)
    segs = gpd.read_parquet(INTERMEDIATE_DIR / "network_segments.parquet")
    print(f"     ukupno segmenata: {len(segs)}", flush=True)
    print(f"     po kategoriji: {segs['kategorija_full'].value_counts().to_dict()}", flush=True)

    # Maknuti sve AC iz GPKG-a
    non_ac = segs[segs["kategorija_full"] != "autocesta"].copy()
    print(f"     ne-AC segmenata: {len(non_ac)}", flush=True)

    # Ucitaj OSM motorway (cista trasa)
    osm_path = INTERMEDIATE_DIR / "osm_motorway.geojson"
    if not osm_path.exists():
        print("[02b] osm_motorway.geojson ne postoji - prvo pokreni 08_fetch_osm_motorway.py", flush=True)
        return
    osm = gpd.read_file(osm_path).to_crs(epsg=CRS_HR)
    print(f"     OSM motorway segmenata: {len(osm)}", flush=True)

    # Izgradi nove AC segmente
    next_id = int(non_ac["seg_id"].max()) + 1 if len(non_ac) else 0
    ac_rows = []
    for _, r in osm.iterrows():
        ref = r.get("ref")
        if not ref:
            continue
        geom = r.geometry
        if geom is None or geom.is_empty:
            continue
        ac_rows.append({
            "seg_id": next_id,
            "oznaka_ceste": ref,
            "kategorija_full": "autocesta",
            "opis_ceste": r.get("name") or "",
            "seg_length_m": float(geom.length),
            "geometry": geom,
        })
        next_id += 1

    ac_gdf = gpd.GeoDataFrame(ac_rows, geometry="geometry", crs=non_ac.crs)
    print(f"     OSM AC segmenata: {len(ac_gdf)}", flush=True)

    combined = pd.concat([non_ac, ac_gdf], ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=non_ac.crs)
    print(f"     Total: {len(combined)} segmenata", flush=True)
    print(f"     po kategoriji: {combined['kategorija_full'].value_counts().to_dict()}", flush=True)

    # Spremi
    out = INTERMEDIATE_DIR / "network_segments.parquet"
    if out.exists():
        try: out.unlink()
        except Exception: pass
    combined.to_parquet(out)
    print(f"[02b] Spremio network_segments.parquet ({len(combined)})", flush=True)
    print("[02b] OK", flush=True)


if __name__ == "__main__":
    main()
