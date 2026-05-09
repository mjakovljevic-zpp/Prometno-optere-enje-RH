"""04 - Izvoz GeoJSON datoteka za web (Leaflet)."""
from __future__ import annotations
import json, shutil, tempfile
from pathlib import Path
import pandas as pd
import geopandas as gpd

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
DATA_DIR = PROJECT_ROOT / "data"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
CRS_HR = 3765
CRS_WGS84 = 4326
SIMPLIFY_M = 8.0


def _safe_write(out_path, write_fn):
    tmp = Path(tempfile.gettempdir()) / ("_cmp_" + out_path.name)
    if tmp.exists():
        try: tmp.unlink()
        except Exception: pass
    write_fn(tmp)
    shutil.copyfile(tmp, out_path)


def main():
    print("[04] Ucitavam segmente s prometom", flush=True)
    seg_traf = gpd.read_parquet(INTERMEDIATE_DIR / "segments_with_traffic.parquet")
    print(f"     {len(seg_traf)} (seg x year) redaka", flush=True)

    traffic_full = pd.read_csv(INTERMEDIATE_DIR / "traffic_long.csv", dtype={"counter_id": str})
    speeds_path = INTERMEDIATE_DIR / "speeds_long.csv"
    speeds = pd.read_csv(speeds_path, dtype={"counter_id": str}) if speeds_path.exists() else pd.DataFrame()

    print("[04] Pivot po segmentima", flush=True)
    base = (
        seg_traf[["seg_id", "oznaka_ceste", "kategorija_full", "opis_ceste",
                  "seg_length_m", "geometry"]]
        .drop_duplicates(subset=["seg_id"]).copy()
    ).set_index("seg_id")

    years = sorted(int(y) for y in seg_traf["year"].dropna().unique())
    pvts = {}
    for k in ("pgdp", "pldp", "confidence", "counter_id", "category", "od", "do"):
        pvts[k] = seg_traf.pivot_table(index="seg_id", columns="year", values=k, aggfunc="first")

    for yr in years:
        base[f"pgdp_{yr}"] = pvts["pgdp"].get(yr) if yr in pvts["pgdp"].columns else None
        base[f"pldp_{yr}"] = pvts["pldp"].get(yr) if yr in pvts["pldp"].columns else None
        base[f"conf_{yr}"] = pvts["confidence"].get(yr) if yr in pvts["confidence"].columns else None
        base[f"cnt_{yr}"] = pvts["counter_id"].get(yr) if yr in pvts["counter_id"].columns else None
        base[f"od_{yr}"] = pvts["od"].get(yr) if yr in pvts["od"].columns else None
        base[f"do_{yr}"] = pvts["do"].get(yr) if yr in pvts["do"].columns else None

    if years:
        last = max(years)
        base["category"] = pvts["category"].get(last) if last in pvts["category"].columns else None

    base = base.reset_index()

    # AC po smjeru
    print("[04] AC po smjeru", flush=True)
    ac_traf = traffic_full[traffic_full["category"] == "AC"].dropna(subset=["section_desc"]).copy()
    sd_pairs = {}
    for _, r in ac_traf.iterrows():
        key = (r["oznaka_ceste"], r["section_desc"])
        sd_pairs.setdefault(key, []).append({
            "counter_id": r["counter_id"], "year": r["year"], "smjer": r.get("smjer"),
            "pgdp": r["pgdp"], "pldp": r["pldp"], "naziv": r["naziv"],
        })
    cnt_to_meta = {}
    for _, r in ac_traf.iterrows():
        cnt_to_meta[(r["counter_id"], r["year"])] = {
            "section_desc": r["section_desc"], "smjer": r.get("smjer"),
            "naziv": r["naziv"],
        }

    for yr in years:
        base[f"pgdp_other_{yr}"] = None
        base[f"pldp_other_{yr}"] = None
        base[f"smjer_{yr}"] = None
        base[f"smjer_other_{yr}"] = None
        for i, row in base.iterrows():
            cnt = row.get(f"cnt_{yr}")
            cat = row.get("category")
            if pd.isna(cnt) or cat != "AC":
                continue
            meta = cnt_to_meta.get((str(cnt), yr))
            if not meta:
                continue
            base.at[i, f"smjer_{yr}"] = meta["smjer"]
            road = row["oznaka_ceste"]
            sd = meta["section_desc"]
            partners = [p for p in sd_pairs.get((road, sd), [])
                        if p["year"] == yr and p["counter_id"] != cnt]
            if partners:
                p = partners[0]
                base.at[i, f"pgdp_other_{yr}"] = p["pgdp"]
                base.at[i, f"pldp_other_{yr}"] = p["pldp"]
                base.at[i, f"smjer_other_{yr}"] = p["smjer"]

    # Brzine
    print("[04] Pripajam brzine", flush=True)
    if len(speeds):
        spd_idx = speeds.set_index(["counter_id", "year"])[
            ["v_avg", "v85_avg", "v_max_dop", "v_avg_smjer1", "v_avg_smjer2"]
        ]
        for yr in [2021, 2022, 2023]:
            base[f"v_avg_{yr}"] = None
            base[f"v_max_{yr}"] = None
            for i, row in base.iterrows():
                cnt = row.get(f"cnt_{yr}")
                if pd.isna(cnt):
                    continue
                try:
                    s = spd_idx.loc[(str(cnt), yr)]
                    if isinstance(s, pd.DataFrame):
                        s = s.iloc[0]
                    base.at[i, f"v_avg_{yr}"] = float(s["v_avg"])
                    md = str(s["v_max_dop"])
                    nums = [int(x) for x in md.split("/") if x.isdigit()]
                    if nums:
                        base.at[i, f"v_max_{yr}"] = max(nums)
                except KeyError:
                    pass

    # Filter
    has_data = base[[f"pgdp_{y}" for y in years]].notna().any(axis=1)
    base = base[has_data].copy()
    print(f"[04] {len(base)} segmenata s podacima", flush=True)

    if not isinstance(base, gpd.GeoDataFrame):
        base = gpd.GeoDataFrame(base, geometry="geometry", crs=f"EPSG:{CRS_HR}")
    base["geometry"] = base.geometry.simplify(tolerance=SIMPLIFY_M, preserve_topology=True)
    base_wgs = base.to_crs(epsg=CRS_WGS84)

    keep = ["seg_id", "oznaka_ceste", "kategorija_full", "opis_ceste",
            "seg_length_m", "category"] + [
        c for c in base_wgs.columns
        if c.startswith(("pgdp_", "pldp_", "conf_", "cnt_", "od_", "do_",
                         "smjer_", "v_avg_", "v_max_"))
    ]
    base_wgs = base_wgs[keep + ["geometry"]]
    for col in keep:
        base_wgs[col] = base_wgs[col].where(pd.notna(base_wgs[col]), None)

    out_geojson = DATA_DIR / "sections.geojson"
    _safe_write(out_geojson, lambda p: base_wgs.to_file(p, driver="GeoJSON"))
    print(f"[04] sections.geojson ({out_geojson.stat().st_size//1024} kB, {len(base_wgs)} feature)", flush=True)

    # Counters layer
    matched = pd.read_csv(INTERMEDIATE_DIR / "counters_matched.csv", dtype={"counter_id": str})
    last_t = traffic_full.sort_values("year").drop_duplicates(subset=["counter_id"], keep="last")
    counters = matched.merge(
        last_t[["counter_id", "pgdp", "pldp", "year", "smjer"]].rename(
            columns={"pgdp": "pgdp_last", "pldp": "pldp_last", "year": "year_last"}),
        on="counter_id", how="left",
    )
    counters_gps = counters.dropna(subset=["lat", "lon"]).copy()
    if len(counters_gps):
        cnt_gdf = gpd.GeoDataFrame(
            counters_gps,
            geometry=gpd.points_from_xy(counters_gps["lon"], counters_gps["lat"]),
            crs=f"EPSG:{CRS_WGS84}",
        )
        cnt_path = DATA_DIR / "counters.geojson"
        _safe_write(cnt_path, lambda p: cnt_gdf.to_file(p, driver="GeoJSON"))
        print(f"[04] counters.geojson ({len(cnt_gdf)})", flush=True)

    # Summary
    summary = {"years": years, "by_year": {},
               "speeds_years": [2021, 2022, 2023] if len(speeds) else []}
    for yr in years:
        col_pg = f"pgdp_{yr}"; col_pl = f"pldp_{yr}"; col_cf = f"conf_{yr}"
        df = base[base[col_pg].notna()]
        cats = df["kategorija_full"].value_counts().to_dict() if len(df) else {}
        confs = df[col_cf].value_counts().to_dict() if (col_cf in df.columns and len(df)) else {}
        summary["by_year"][yr] = {
            "n_sections": int(len(df)),
            "total_length_km": float(df["seg_length_m"].sum() / 1000.0) if len(df) else 0.0,
            "avg_pgdp": float(df[col_pg].mean()) if len(df) else None,
            "avg_pldp": float(df[col_pl].mean()) if (len(df) and col_pl in df.columns) else None,
            "max_pgdp": float(df[col_pg].max()) if len(df) else None,
            "max_pldp": float(df[col_pl].max()) if (len(df) and col_pl in df.columns) else None,
            "by_category": {str(k): int(v) for k, v in cats.items()},
            "by_confidence": {str(k): int(v) for k, v in confs.items()},
        }

    sum_path = DATA_DIR / "summary.json"
    def _w(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    _safe_write(sum_path, _w)
    print("[04] summary.json", flush=True)

    mo_path = DATA_DIR / "manual_overrides.csv"
    if not mo_path.exists():
        def _wmo(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write("counter_id,year,seg_ids,note\n")
                f.write("# Primjer: 1101,2024,123;124;125,Rucno definirana dionica\n")
        _safe_write(mo_path, _wmo)
        print("[04] manual_overrides.csv (predlozak)", flush=True)

    print("[04] OK", flush=True)


if __name__ == "__main__":
    main()
