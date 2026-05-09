"""03b - Dodjela AC brojaca segmentima bez GPS-a.

Logika: AC brojaci nemaju GPS u lokacijskoj tablici Hrvatskih cesta. Cesta
u XLS-u redoslijed brojaca prati fizicki redoslijed duz autoceste. Stoga:
1) Uzmi sve AC brojace iz traffic_long, sortirane po unutarnjem redoslijedu
2) Linmerge geometriju cijele autoceste, projektiraj na nju brojace u
   ravnomjernom rasporedu (po section_desc redoslijedu)
3) Dodaj rezultate u segments_with_traffic.parquet (ne brisemo postojece
   non-AC zapise iz skripte 03).

Pokrece se NAKON skripte 03.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import geopandas as gpd
from shapely.ops import linemerge, unary_union

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"


def main():
    print("[03b] Ucitavam podatke", flush=True)
    segs = gpd.read_parquet(INTERMEDIATE_DIR / "network_segments.parquet")
    traffic = pd.read_csv(INTERMEDIATE_DIR / "traffic_long.csv", dtype={"counter_id": str})
    seg_traf = gpd.read_parquet(INTERMEDIATE_DIR / "segments_with_traffic.parquet")

    # Skupina po (oznaka_ceste) za AC. Brojaci se mogu pojaviti vise puta (jednom po godini, oba smjera).
    ac = traffic[traffic["category"] == "AC"].copy()
    print(f"     AC retke: {len(ac)}", flush=True)

    # AC mreza
    ac_segs = segs[segs["kategorija_full"] == "autocesta"].copy()
    print(f"     AC segmenti: {len(ac_segs)}", flush=True)

    # Po cestama
    out_rows = []
    for road, ac_road in ac.groupby("oznaka_ceste"):
        road_segs = ac_segs[ac_segs["oznaka_ceste"] == road]
        if road_segs.empty:
            continue
        # spojena geometrija
        geoms = list(road_segs.geometry)
        merged = linemerge(unary_union(geoms))

        # Sortiraj brojace na ovoj cesti — pretpostavi da je redoslijed u XLS
        # logican (po section_desc nazivu ili counter_id). Uzmi unique section
        # opise i njihovu rangu.
        unique_sd = ac_road.drop_duplicates(subset=["section_desc"]).copy()
        # Ako section_desc moze biti sortirano abecedno, OK. Inace koristi
        # counter_id rangu unutar svojih AC brojaca.
        unique_sd = unique_sd.sort_values(["counter_id"])
        sd_list = unique_sd["section_desc"].tolist()

        if not sd_list:
            continue
        n = len(sd_list)
        # Podijeli ukupnu duljinu na n dijelova; za svaki segment, na temelju
        # centroidne "measure" odredi kojoj se sekciji dodjeljuje.
        try:
            total_len = merged.length if hasattr(merged, "length") else sum(g.length for g in merged.geoms)
        except Exception:
            total_len = sum(g.length for g in geoms)
        if total_len <= 0:
            continue
        # Bin granice na svakoj 1/n duljine
        boundaries = [(i + 1) * total_len / n for i in range(n - 1)]

        # Za svaki segment ove ceste — projeciraj centroid
        for _, sg in road_segs.iterrows():
            try:
                centroid = sg.geometry.interpolate(0.5, normalized=True)
                if hasattr(merged, "geom_type") and merged.geom_type == "MultiLineString":
                    # uzmi najblizu komponentu
                    best_d = None
                    best_m = 0.0
                    cum = 0.0
                    for ln in merged.geoms:
                        d = centroid.distance(ln)
                        if best_d is None or d < best_d:
                            best_d = d
                            try:
                                best_m = cum + ln.project(centroid)
                            except Exception:
                                best_m = cum
                        cum += ln.length
                    m = best_m
                else:
                    m = merged.project(centroid)
            except Exception:
                continue
            # Odredi sekciju
            sec_idx = 0
            for j, b in enumerate(boundaries):
                if m > b:
                    sec_idx = j + 1
            if sec_idx >= n:
                sec_idx = n - 1
            sd = sd_list[sec_idx]

            # Za svaki par (counter_id, year) s tim section_desc, dodaj redak
            sub = ac_road[ac_road["section_desc"] == sd]
            for _, r in sub.iterrows():
                out_rows.append({
                    "seg_id": int(sg["seg_id"]),
                    "year": int(r["year"]),
                    "counter_id": str(r["counter_id"]),
                    "pgdp": r["pgdp"],
                    "pldp": r["pldp"],
                    "od": r.get("od"),
                    "do": r.get("do"),
                    "section_desc": sd,
                    "category": "AC",
                    "confidence": "low",
                    "oznaka_ceste": road,
                    "kategorija_full": "autocesta",
                    "opis_ceste": sg.get("opis_ceste"),
                    "seg_length_m": float(sg["seg_length_m"]),
                    "geometry": sg.geometry,
                })

    if not out_rows:
        print("[03b] Nema AC redaka za dodati.", flush=True)
        return

    new_ac = gpd.GeoDataFrame(out_rows, geometry="geometry", crs=segs.crs)
    print(f"[03b] Novih AC zapisa: {len(new_ac)}", flush=True)

    # Pri spajanju s postojecim seg_traf-om: maknuti AC retke iz starog (ako su Voronoi-jevi)
    seg_traf = seg_traf[seg_traf["kategorija_full"] != "autocesta"].copy()
    # Dosta podaci se podudaraju; spoji sve
    combined = pd.concat([seg_traf, new_ac[seg_traf.columns]], ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=segs.crs)

    # Prepisi parquet (preko /tmp ako treba)
    out = INTERMEDIATE_DIR / "segments_with_traffic.parquet"
    if out.exists():
        try: out.unlink()
        except Exception: pass
    combined.to_parquet(out)
    print(f"[03b] Spremio combined ({len(combined)})", flush=True)
    print("[03b] OK", flush=True)


if __name__ == "__main__":
    main()
