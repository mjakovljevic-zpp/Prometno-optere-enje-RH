"""04 - Izvoz GeoJSON datoteka za web (Leaflet).

Generira:
  data/sections.geojson  - segmenti s prometnim atributima
  data/counters.geojson  - tocke brojaca (lat/lon)
  data/summary.json      - sazetak za dashboard
  data/manual_overrides.csv - prazna predloska
"""
from __future__ import annotations
import json
import shutil
import tempfile
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
    """Zapisi preko tmp -> shutil.copyfile da se izbjegnu permission problemi."""
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

    print("[04] Pivot po segmentima", flush=True)
    base = (
        seg_traf[["seg_id", "oznaka_ceste", "kategorija_full",
                  "opis_ceste", "seg_length_m", "geometry"]]
        .drop_duplicates(subset=["seg_id"])
        .copy()
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
        if c.startswith(("pgdp_", "pldp_", "conf_", "cnt_", "od_", "do_"))
    ]
    base_wgs = base_wgs[keep + ["geometry"]]
    for col in keep:
        base_wgs[col] = base_wgs[col].where(pd.notna(base_wgs[col]), None)

    out_geojson = DATA_DIR / "sections.geojson"
    _safe_write(out_geojson, lambda p: base_wgs.to_file(p, driver="GeoJSON"))
    sz = out_geojson.stat().st_size / 1024
    print(f"[04] sections.geojson ({sz:.0f} kB, {len(base_wgs)} feature)", flush=True)

    matched = pd.read_csv(INTERMEDIATE_DIR / "counters_matched.csv", dtype={"counter_id": str})
    traffic = pd.read_csv(INTERMEDIATE_DIR / "traffic_long.csv", dtype={"counter_id": str})
    last_t = traffic.sort_values("year").drop_duplicates(subset=["counter_id"], keep="last")
    counters = matched.merge(
        last_t[["counter_id", "pgdp", "pldp", "year"]].rename(
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

    summary = {"years": years, "by_year": {}}
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
