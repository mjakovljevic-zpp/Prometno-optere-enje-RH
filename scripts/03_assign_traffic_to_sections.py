"""03 - Dodjela PGDP/PLDP vrijednosti cestovnim segmentima.

Algoritam (ukratko):
1. Za svaku cestu (oznaka_ceste) sakupi sve njene segmente iz mreze
2. Sakupi sve brojace koji se odnose na tu cestu (po imenu)
3. Linearno referenciraj brojace duz ceste (linear referencing)
4. Pokusaj odrediti pocetni i krajnji "rub" dionice koristenjem Od/Do referenci
   - Trazimo geometriju Od/Do ceste i njeno krizanje s home-cestom
5. Za svaki segment, odredi kojoj dionici (brojacu) najbolje pripada:
   - U dosegu njegovog Od-Do raspona => taj brojac
   - Inace: najblizi brojac na istoj cesti (Voronoi-style po linear measure)
6. Brojaci bez GPS-a: dodjeljuju vrijednost cijeloj cesti (kategorija "whole road")

Confidence:
  high   = brojac s GPS-om i Od/Do prostorno locirani; segment u rasponu
  medium = brojac s GPS-om, ali Od/Do referenca neidentificirana; Voronoi
  low    = brojac bez GPS-a, dodjela cijele ceste
  none   = ne moze se dodijeliti

Manual overrides (data/manual_overrides.csv) - opcionalno:
  counter_id,year,seg_ids,note
  npr. "1101,2023,123;124;125,Rucno definirano"
  Override ce zamijeniti automatsku dodjelu za taj counter+godinu.

Izlaz (data/intermediate/):
  segments_with_traffic.parquet  - per-segment x godina, atributi
  segments_with_traffic.geojson  - isto, ali za web (samo zadnja godina ili kombinirano)
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.ops import linemerge, unary_union
from shapely.geometry import LineString, MultiLineString, Point

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
RAW_ROOT = PROJECT_ROOT.parent
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"
DATA_DIR = PROJECT_ROOT / "data"
MANUAL_OVERRIDES = DATA_DIR / "manual_overrides.csv"

CRS_HR = 3765
CRS_WGS84 = 4326


def _measure_along(line, point):
    """Vrati linear referencing measure (m) tocke na liniji."""
    try:
        return float(line.project(point))
    except Exception:
        return None


def _build_road_geometry(segs_for_road):
    """Spoji sve segmente jedne ceste u jednu LineString (ako moguce) ili MultiLineString."""
    geoms = list(segs_for_road.geometry)
    if not geoms:
        return None
    if len(geoms) == 1:
        return geoms[0]
    merged = linemerge(unary_union(geoms))
    return merged


def _intersection_with_road(home_geom, ref_geom):
    """Vrati listu Point-ova gdje home_geom sijece ref_geom."""
    if home_geom is None or ref_geom is None:
        return []
    try:
        inter = home_geom.intersection(ref_geom)
    except Exception:
        return []
    if inter.is_empty:
        return []
    pts = []
    if inter.geom_type == "Point":
        pts.append(inter)
    elif inter.geom_type == "MultiPoint":
        pts.extend(list(inter.geoms))
    elif inter.geom_type in ("LineString", "MultiLineString"):
        if inter.geom_type == "LineString":
            for c in inter.coords:
                pts.append(Point(c))
        else:
            for ln in inter.geoms:
                for c in ln.coords:
                    pts.append(Point(c))
    elif inter.geom_type.startswith("GeometryCollection"):
        for g in inter.geoms:
            if g.geom_type == "Point":
                pts.append(g)
    return pts


def main():
    print("[03] Ucitavam segmente i brojace", flush=True)
    segs = gpd.read_parquet(INTERMEDIATE_DIR / "network_segments.parquet")
    if str(segs.crs).upper() != f"EPSG:{CRS_HR}":
        segs = segs.to_crs(epsg=CRS_HR)
    matched = pd.read_csv(INTERMEDIATE_DIR / "counters_matched.csv", dtype={"counter_id": str})
    traffic = pd.read_csv(INTERMEDIATE_DIR / "traffic_long.csv", dtype={"counter_id": str})
    print(f"     {len(segs)} segmenata, {len(matched)} brojaca s GPS, {len(traffic)} prometnih redaka", flush=True)

    # Brz lookup: oznaka_ceste -> spojena geometrija ceste
    print("[03] Gradim spojenu geometriju po cesti", flush=True)
    road_geom = {}
    for road, sub in segs.groupby("oznaka_ceste"):
        road_geom[road] = _build_road_geometry(sub)

    # Brz lookup brojaca koji su uspjesno geo-locirani
    counter_loc = {}  # counter_id -> (oznaka_ceste, point_geom)
    for _, r in matched.iterrows():
        if pd.notna(r.get("matched_oznaka_ceste")) and pd.notna(r.get("lat")) and pd.notna(r.get("lon")):
            pt = gpd.GeoSeries([Point(r["lon"], r["lat"])], crs=f"EPSG:{CRS_WGS84}").to_crs(epsg=CRS_HR).iloc[0]
            counter_loc[r["counter_id"]] = (r["matched_oznaka_ceste"], pt)

    # Posebna struktura: za svaku cestu lista (counter_id, measure_m, od, do)
    print("[03] Gradim domene brojaca po cesti", flush=True)
    counters_by_road = {}
    for cid, (road, pt) in counter_loc.items():
        line = road_geom.get(road)
        if line is None:
            continue
        m = _measure_along(line, pt)
        if m is None:
            continue
        counters_by_road.setdefault(road, []).append((cid, m, pt))

    # Sortiraj brojace duz svake ceste
    for road, lst in counters_by_road.items():
        lst.sort(key=lambda x: x[1])

    # Ucitaj manual overrides ako postoje
    overrides = {}
    if MANUAL_OVERRIDES.exists():
        try:
            ov_df = pd.read_csv(MANUAL_OVERRIDES, dtype={"counter_id": str, "year": int})
            for _, r in ov_df.iterrows():
                key = (r["counter_id"], int(r["year"]) if pd.notna(r.get("year")) else None)
                seg_ids = [int(x) for x in str(r["seg_ids"]).split(";") if x.strip()]
                overrides[key] = seg_ids
            print(f"[03] Ucitao {len(overrides)} ovveride zapisa", flush=True)
        except Exception as e:
            print(f"[03] Override CSV problem: {e}", flush=True)

    # Sad za svaku cestu odredi koji brojac "vlada" kojim segmentom
    # Pristup: za svaki segment uzmi sredisnju tocku i vidi koji je najblizi brojac na istoj cesti
    # po linear measure (Voronoi-style)
    print("[03] Dodjeljujem segmente brojacima", flush=True)
    seg_owner = {}  # seg_id -> (counter_id, confidence)
    for road, lst in counters_by_road.items():
        if not lst:
            continue
        line = road_geom.get(road)
        if line is None:
            continue
        sub_segs = segs[segs["oznaka_ceste"] == road]
        # Voronoi granice po measure: midpoints izmedju susjednih brojaca
        cids = [x[0] for x in lst]
        meas = np.array([x[1] for x in lst])
        if len(meas) == 1:
            # Jedini brojac - cijela cesta njegova
            for sid in sub_segs["seg_id"]:
                seg_owner[sid] = (cids[0], "medium")
            continue
        midpoints = (meas[:-1] + meas[1:]) / 2.0
        # bins: -inf < midpoints[0] < ... < midpoints[-1] < +inf
        for _, sg in sub_segs.iterrows():
            sid = sg["seg_id"]
            try:
                centroid = sg.geometry.interpolate(0.5, normalized=True)
                m_seg = line.project(centroid)
            except Exception:
                continue
            owner_idx = np.searchsorted(midpoints, m_seg, side="right")
            if owner_idx >= len(cids):
                owner_idx = len(cids) - 1
            seg_owner[sid] = (cids[owner_idx], "medium")

    # Brojaci bez GPS-a koji imaju ipak `oznaka_ceste` => "whole road" fallback
    counters_no_gps = matched[matched["lat"].isna() | matched["lon"].isna()]
    # Pravi izvor cest-ime: counter_id -> oznaka_ceste iz traffic tabele
    cid_to_road = (
        traffic.dropna(subset=["oznaka_ceste"])
        .drop_duplicates(subset=["counter_id"])
        .set_index("counter_id")["oznaka_ceste"].to_dict()
    )
    # Za one koji nisu vec u counters_by_road (tj. nema GPS), ako njihov oznaka_ceste
    # postoji u mrezi - pripisi cijeloj cesti samo ako tu cestu nitko drugi (s GPS-om) ne drzi
    held_roads = {road for road in counters_by_road.keys() if counters_by_road[road]}
    for cid, road in cid_to_road.items():
        if cid in counter_loc:
            continue
        if road not in road_geom:
            continue
        if road in held_roads:
            # Vec netko drugi pokriva cestu detaljnije - preskoci da ne mjesamo
            continue
        sub_segs = segs[segs["oznaka_ceste"] == road]
        for sid in sub_segs["seg_id"]:
            seg_owner.setdefault(sid, (cid, "low"))

    # Manual overrides idu zadnji - prepisuju
    for (cid, year), seg_ids in overrides.items():
        for sid in seg_ids:
            # Po godini moze ovisiti, no zelimo brzi prikaz - radimo "uvijek primijeni"
            seg_owner[sid] = (cid, "high")
    if overrides:
        print(f"[03] Primijenjeno {sum(len(v) for v in overrides.values())} override segmenata", flush=True)

    # Promet po (counter_id, year) -> PGDP, PLDP
    print("[03] Spajam segmente s prometnim podacima po godini", flush=True)
    traffic_idx = traffic.set_index(["counter_id", "year"])[
        ["pgdp", "pldp", "od", "do", "section_desc", "category"]
    ]

    # Build long output: jedan red po (seg_id, year)
    rows = []
    years = sorted(traffic["year"].dropna().unique().tolist())
    for sid, (cid, conf) in seg_owner.items():
        for yr in years:
            try:
                t = traffic_idx.loc[(cid, yr)]
            except KeyError:
                continue
            pgdp = t["pgdp"] if not isinstance(t, pd.DataFrame) else (t["pgdp"].iloc[0] if len(t) else None)
            pldp = t["pldp"] if not isinstance(t, pd.DataFrame) else (t["pldp"].iloc[0] if len(t) else None)
            od = t["od"] if not isinstance(t, pd.DataFrame) else (t["od"].iloc[0] if len(t) else None)
            do = t["do"] if not isinstance(t, pd.DataFrame) else (t["do"].iloc[0] if len(t) else None)
            sd = t["section_desc"] if not isinstance(t, pd.DataFrame) else (t["section_desc"].iloc[0] if len(t) else None)
            cat = t["category"] if not isinstance(t, pd.DataFrame) else (t["category"].iloc[0] if len(t) else None)
            rows.append({
                "seg_id": sid,
                "year": yr,
                "counter_id": cid,
                "pgdp": pgdp,
                "pldp": pldp,
                "od": od,
                "do": do,
                "section_desc": sd,
                "category": cat,
                "confidence": conf,
            })
    seg_traffic = pd.DataFrame(rows)
    print(f"[03] {len(seg_traffic)} (seg x godina) zapisa, {seg_traffic['seg_id'].nunique()} segmenata pokriveno", flush=True)

    # Spoji s geometrijom
    out = segs.merge(seg_traffic, on="seg_id", how="left")
    out_path = INTERMEDIATE_DIR / "segments_with_traffic.parquet"
    if out_path.exists():
        try:
            out_path.unlink()
        except Exception:
            pass
    out.to_parquet(out_path)
    print(f"[03] Spremio segments_with_traffic.parquet ({len(out)})", flush=True)
    print("[03] OK", flush=True)


if __name__ == "__main__":
    main()
