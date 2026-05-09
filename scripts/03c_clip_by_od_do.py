"""03c - Brzo Od/Do clipanje za DC/ZC/LC.

Optimizacija: za svaku cestu izgradi spojenu geometriju i pre-cache
centroid measure svakog segmenta. Onda za svaki brojac jednostavno
nadji measure za Od i Do referentne ceste i klipni segmente.
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
    print("[03c] Ucitavam", flush=True)
    segs = gpd.read_parquet(INTERMEDIATE_DIR / "network_segments.parquet")
    seg_traf = gpd.read_parquet(INTERMEDIATE_DIR / "segments_with_traffic.parquet")
    matched = pd.read_csv(INTERMEDIATE_DIR / "counters_matched.csv", dtype={"counter_id": str})
    traffic = pd.read_csv(INTERMEDIATE_DIR / "traffic_long.csv", dtype={"counter_id": str})

    print("[03c] Pre-cache road geom + seg measures", flush=True)
    road_geom = {}
    road_comps = {}
    seg_measure_by_road = {}  # road -> {seg_id: measure}

    for road, sub in segs.groupby("oznaka_ceste"):
        geoms = [g for g in sub.geometry if g is not None and not g.is_empty]
        if not geoms:
            continue
        merged = linemerge(unary_union(geoms)) if len(geoms) > 1 else geoms[0]
        comps = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
        road_geom[road] = merged
        road_comps[road] = comps
        # Pre-compute seg centroid measures
        sm = {}
        for _, sg in sub.iterrows():
            try:
                ctr = sg.geometry.interpolate(0.5, normalized=True)
                cum = 0.0
                best_d = None
                best_m = 0.0
                for ln in comps:
                    d = ctr.distance(ln)
                    if best_d is None or d < best_d:
                        best_d = d
                        try:
                            best_m = cum + ln.project(ctr)
                        except Exception:
                            best_m = cum
                    cum += ln.length
                sm[int(sg["seg_id"])] = best_m
            except Exception:
                pass
        seg_measure_by_road[road] = sm

    print(f"     {len(road_geom)} cesta indeksirano", flush=True)

    def measure_on_road(road, point):
        comps = road_comps.get(road)
        if not comps:
            return None
        cum = 0.0
        best_d = None
        best_m = None
        for ln in comps:
            d = point.distance(ln)
            if best_d is None or d < best_d:
                best_d = d
                try:
                    best_m = cum + ln.project(point)
                except Exception:
                    best_m = cum
            cum += ln.length
        return best_m

    def first_intersection(home_road, ref_code):
        if not ref_code or pd.isna(ref_code):
            return None
        ref_geom = road_geom.get(ref_code)
        home = road_geom.get(home_road)
        if ref_geom is None or home is None:
            return None
        try:
            inter = home.intersection(ref_geom)
        except Exception:
            return None
        if inter.is_empty:
            return None
        if inter.geom_type == "Point":
            return inter
        if inter.geom_type == "MultiPoint":
            return list(inter.geoms)[0]
        try:
            return inter.representative_point()
        except Exception:
            return None

    matched_dc = matched[matched["category"].isin(["DC", "ZC", "LC"])].dropna(subset=["matched_oznaka_ceste"])
    last_t = (
        traffic[traffic["category"].isin(["DC", "ZC", "LC"])]
        .sort_values("year")
        .drop_duplicates(subset=["counter_id"], keep="last")
    )
    cid_to_od_do = last_t.set_index("counter_id")[["od", "do"]].to_dict("index")

    print("[03c] Klipanje", flush=True)
    new_assignments = {}  # seg_id -> (counter_id, conf)
    n_high = 0
    for _, row in matched_dc.iterrows():
        cid = row["counter_id"]
        home = row["matched_oznaka_ceste"]
        if home not in road_geom:
            continue
        od_do = cid_to_od_do.get(cid)
        if not od_do:
            continue
        p_od = first_intersection(home, od_do.get("od"))
        p_do = first_intersection(home, od_do.get("do"))
        if p_od is None or p_do is None:
            continue
        m_od = measure_on_road(home, p_od)
        m_do = measure_on_road(home, p_do)
        if m_od is None or m_do is None:
            continue
        m_lo, m_hi = sorted([m_od, m_do])
        sm = seg_measure_by_road.get(home, {})
        for sid, m_seg in sm.items():
            if m_lo <= m_seg <= m_hi:
                cur = new_assignments.get(sid)
                if cur is None or cur[1] != "high":
                    new_assignments[sid] = (cid, "high")
                    n_high += 1
    print(f"     dodijeljeno {n_high} (seg x brojač) novih high-confidence parova", flush=True)

    if not new_assignments:
        print("[03c] Nema sto za primijeniti.", flush=True)
        return

    t_idx = traffic.set_index(["counter_id", "year"])[
        ["pgdp", "pldp", "od", "do", "section_desc", "category"]
    ]
    affected = set(new_assignments.keys())
    keep_mask = ~(seg_traf["seg_id"].isin(affected) &
                  seg_traf["kategorija_full"].isin(["državna cesta", "županijska cesta", "lokalna cesta"]))
    keep = seg_traf[keep_mask].copy()
    print(f"     drzim {len(keep)} starih, dodajem nove zapise...", flush=True)

    new_rows = []
    years = sorted(traffic["year"].dropna().unique())
    seg_lookup = segs.set_index("seg_id")
    for sid, (cid, conf) in new_assignments.items():
        if sid not in seg_lookup.index:
            continue
        sg = seg_lookup.loc[sid]
        for yr in years:
            try:
                t = t_idx.loc[(cid, yr)]
                if isinstance(t, pd.DataFrame):
                    t = t.iloc[0]
                new_rows.append({
                    "seg_id": int(sid), "year": int(yr), "counter_id": cid,
                    "pgdp": t["pgdp"], "pldp": t["pldp"],
                    "od": t.get("od"), "do": t.get("do"),
                    "section_desc": t.get("section_desc"),
                    "category": t.get("category"),
                    "confidence": conf,
                    "oznaka_ceste": sg["oznaka_ceste"],
                    "kategorija_full": sg["kategorija_full"],
                    "opis_ceste": sg.get("opis_ceste"),
                    "seg_length_m": float(sg["seg_length_m"]),
                    "geometry": sg.geometry,
                })
            except KeyError:
                continue

    new_df = gpd.GeoDataFrame(new_rows, geometry="geometry", crs=segs.crs)
    combined = pd.concat([keep, new_df[keep.columns]], ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=segs.crs)

    out = INTERMEDIATE_DIR / "segments_with_traffic.parquet"
    if out.exists():
        try: out.unlink()
        except Exception: pass
    combined.to_parquet(out)
    print(f"[03c] Spremio combined ({len(combined)})", flush=True)
    print("[03c] OK", flush=True)


if __name__ == "__main__":
    main()
