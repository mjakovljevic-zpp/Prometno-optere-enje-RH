"""03b - Dodjela AC brojaca segmentima koristeci OSM motorway_junction cvorove.

Logika:
1) Ucitaj OSM cvorove (data/intermediate/osm_junctions.geojson)
2) Za svaki AC brojac, parse 'cv. X - cv. Y' iz section_desc
3) Pronadji X i Y u OSM tablici po imenu (fuzzy)
4) Spoji geometriju autoceste (linemerge)
5) Project oba cvora na liniju, dobij measure pocetka i kraja
6) Pripisi sve segmente cije se sredine nalaze izmedju tih measureva tom brojacu
7) Confidence: high (oba cvora), medium (jedan), low (nijedan - fallback proporcionalno)
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path
import pandas as pd
import geopandas as gpd
from shapely.ops import linemerge, unary_union
from shapely.geometry import Point

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"

CRS_HR = 3765
CRS_WGS84 = 4326


def normalize(s):
    """Strip accents + lowercase za fuzzy match imena cvorova."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def parse_cvor_names(text):
    """Iz 'cv. Lucko - cv. Zdencina' vrati ('Lucko', 'Zdencina')."""
    if pd.isna(text) or not text:
        return None, None
    s = str(text).strip()
    parts = re.split(r"\s+[-–]\s+", s, maxsplit=1)
    if len(parts) != 2:
        return None, None
    a, b = parts[0].strip(), parts[1].strip()
    a = re.sub(r"^[čcČC]v\.\s*", "", a)
    b = re.sub(r"^[čcČC]v\.\s*", "", b)
    a = re.sub(r"\s*\([^)]*\)\s*$", "", a)
    b = re.sub(r"\s*\([^)]*\)\s*$", "", b)
    return a or None, b or None


def find_junction_point(name, junctions_norm, junctions_gs):
    """Vrati shapely Point za zadano ime cvora ili None."""
    if not name:
        return None
    n = normalize(name)
    # tocan match
    if n in junctions_norm:
        idx = junctions_norm[n]
        return junctions_gs.iloc[idx].geometry
    # substring match
    for k, idx in junctions_norm.items():
        if k.startswith(n) or n.startswith(k) or k.find(n) >= 0:
            return junctions_gs.iloc[idx].geometry
    return None


def main():
    print("[03b] Ucitavam podatke", flush=True)
    segs = gpd.read_parquet(INTERMEDIATE_DIR / "network_segments.parquet")
    traffic = pd.read_csv(INTERMEDIATE_DIR / "traffic_long.csv", dtype={"counter_id": str})
    seg_traf = gpd.read_parquet(INTERMEDIATE_DIR / "segments_with_traffic.parquet")

    # Ucitaj OSM cvorove
    osm_path = INTERMEDIATE_DIR / "osm_junctions.geojson"
    if not osm_path.exists():
        print("[03b] Nema osm_junctions.geojson - prvo pokreni 07_fetch_osm_junctions.py", flush=True)
        return
    junctions = gpd.read_file(osm_path).to_crs(epsg=CRS_HR)
    print(f"     OSM cvorovi: {len(junctions)}", flush=True)

    # Index po normaliziranom imenu (zadrzi prvog)
    junctions_norm = {}
    for i, row in junctions.iterrows():
        n = normalize(row.get("name") or "")
        if n and n not in junctions_norm:
            junctions_norm[n] = i

    # AC mreza
    ac_segs = segs[segs["kategorija_full"] == "autocesta"].copy()
    ac = traffic[traffic["category"] == "AC"].copy()
    print(f"     AC segs: {len(ac_segs)}, AC retke: {len(ac)}", flush=True)

    out_rows = []
    stats = {"high": 0, "medium": 0, "low": 0, "no_road": 0}

    for road, ac_road in ac.groupby("oznaka_ceste"):
        road_segs = ac_segs[ac_segs["oznaka_ceste"] == road]
        if road_segs.empty:
            stats["no_road"] += len(ac_road)
            continue

        geoms = list(road_segs.geometry)
        merged = linemerge(unary_union(geoms))
        # measure utility
        if hasattr(merged, "geom_type") and merged.geom_type == "MultiLineString":
            comps = list(merged.geoms)
        else:
            comps = [merged]

        def measure_on(point):
            best_d = None
            best_m = None
            cum = 0.0
            for ln in comps:
                d = point.distance(ln)
                if best_d is None or d < best_d:
                    best_d = d
                    try:
                        best_m = cum + ln.project(point)
                    except Exception:
                        best_m = cum
                cum += ln.length
            return best_m, best_d

        # Pripremi sve seg centroid measurea
        seg_measures = {}
        for _, sg in road_segs.iterrows():
            try:
                ctr = sg.geometry.interpolate(0.5, normalized=True)
                m, _ = measure_on(ctr)
                seg_measures[int(sg["seg_id"])] = m if m is not None else 0.0
            except Exception:
                pass

        unique_sd = ac_road.drop_duplicates(subset=["section_desc"]).copy()

        # Za svaki section, pronadji granice po OSM cvorovima
        bounds = {}  # section_desc -> (m_start, m_end, conf)
        for _, srow in unique_sd.iterrows():
            sd = srow["section_desc"]
            a, b = parse_cvor_names(sd)
            ja = find_junction_point(a, junctions_norm, junctions) if a else None
            jb = find_junction_point(b, junctions_norm, junctions) if b else None
            if ja and jb:
                ma, _ = measure_on(ja)
                mb, _ = measure_on(jb)
                if ma is not None and mb is not None:
                    bounds[sd] = (min(ma, mb), max(ma, mb), "high")
                    continue
            if ja or jb:
                pt = ja or jb
                m, _ = measure_on(pt)
                if m is not None:
                    # 5km u oba smjera oko jedne točke
                    bounds[sd] = (max(0, m - 5000), m + 5000, "medium")
                    continue
            bounds[sd] = (None, None, "low")

        # Sortiraj sekcije po start measure (gdje su poznate)
        sorted_sd = sorted(unique_sd["section_desc"].tolist(),
                           key=lambda x: (bounds[x][0] if bounds[x][0] is not None else float("inf")))

        # Za 'low' sekcije bez granica, fallback proporcionalno
        low_sds = [sd for sd in sorted_sd if bounds[sd][2] == "low"]
        if low_sds and seg_measures:
            total_low = len(low_sds)
            total_len = max(seg_measures.values())
            # Distribuiraj ravnomjerno preko cijele duljine
            for i, sd in enumerate(low_sds):
                bounds[sd] = (i * total_len / total_low,
                              (i + 1) * total_len / total_low, "low")

        # Pripisi segmente
        for sid, m_seg in seg_measures.items():
            chosen_sd = None
            chosen_conf = None
            for sd in sorted_sd:
                m_start, m_end, conf = bounds[sd]
                if m_start is None:
                    continue
                if m_start <= m_seg <= m_end:
                    if chosen_conf is None or conf == "high":
                        chosen_sd = sd
                        chosen_conf = conf
                        if conf == "high":
                            break
            if chosen_sd is None:
                # Najblizoj sekciji po sredini
                best = None
                best_d = None
                for sd in sorted_sd:
                    m_start, m_end, _ = bounds[sd]
                    if m_start is None:
                        continue
                    mid = (m_start + m_end) / 2
                    d = abs(mid - m_seg)
                    if best is None or d < best_d:
                        best = sd
                        best_d = d
                if best:
                    chosen_sd = best
                    chosen_conf = "low"

            if chosen_sd is None:
                continue

            sg = road_segs[road_segs["seg_id"] == sid].iloc[0]
            sub = ac_road[ac_road["section_desc"] == chosen_sd]
            for _, r in sub.iterrows():
                out_rows.append({
                    "seg_id": int(sid),
                    "year": int(r["year"]),
                    "counter_id": str(r["counter_id"]),
                    "pgdp": r["pgdp"],
                    "pldp": r["pldp"],
                    "od": r.get("od"),
                    "do": r.get("do"),
                    "section_desc": chosen_sd,
                    "category": "AC",
                    "confidence": chosen_conf,
                    "oznaka_ceste": road,
                    "kategorija_full": "autocesta",
                    "opis_ceste": sg.get("opis_ceste"),
                    "seg_length_m": float(sg["seg_length_m"]),
                    "geometry": sg.geometry,
                })
                stats[chosen_conf] = stats.get(chosen_conf, 0) + 1

    print(f"[03b] Confidence: {stats}", flush=True)

    if not out_rows:
        print("[03b] Nema AC redaka.", flush=True)
        return

    new_ac = gpd.GeoDataFrame(out_rows, geometry="geometry", crs=segs.crs)
    seg_traf = seg_traf[seg_traf["kategorija_full"] != "autocesta"].copy()
    combined = pd.concat([seg_traf, new_ac[seg_traf.columns]], ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry="geometry", crs=segs.crs)

    out = INTERMEDIATE_DIR / "segments_with_traffic.parquet"
    if out.exists():
        try: out.unlink()
        except Exception: pass
    combined.to_parquet(out)
    print(f"[03b] Spremio combined ({len(combined)})", flush=True)
    print("[03b] OK", flush=True)


if __name__ == "__main__":
    main()
