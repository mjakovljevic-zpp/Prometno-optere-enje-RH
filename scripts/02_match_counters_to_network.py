"""02 - Prostorno spajanje brojaca s cestovnom mrezom.

Za svaki brojac s GPS-om:
1) Pokusava egzaktno spajanje po `oznaka_ceste` s GPKG mrezom.
2) Ako nema match po imenu, fallback najblizi segment u krugu MAX_NEAREST_M.

Izlaz (data/intermediate/):
  counters_matched.csv         - per-counter rezultat matchinga
  unmatched_counters.geojson   - brojaci bez prostornog matcha (za pregled)
  network_segments.parquet     - eksplodirani LineString segmenti mreze
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import geopandas as gpd

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
RAW_ROOT = PROJECT_ROOT.parent
NETWORK_GPKG = RAW_ROOT / "Mreza cesta" / "20250625_091453_cesta.gpkg"
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"
INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

CRS_HR = 3765
CRS_WGS84 = 4326
MAX_NEAREST_M = 250.0


def main():
    print("[02] Ucitavam mrezu cesta", flush=True)
    network = gpd.read_file(NETWORK_GPKG)
    network = network.rename(columns={
        "oznaka ceste": "oznaka_ceste",
        "kategorija": "kategorija_full",
        "opis ceste": "opis_ceste",
    })
    print(f"     {len(network)} cesta, CRS: {network.crs}", flush=True)
    if str(network.crs).upper() != f"EPSG:{CRS_HR}":
        network = network.to_crs(epsg=CRS_HR)

    print("[02] Eksplodiram MultiLineString u segmente", flush=True)
    segs = network.explode(index_parts=False, ignore_index=True)
    segs["seg_id"] = range(len(segs))
    segs["seg_length_m"] = segs.geometry.length
    print(f"     {len(segs)} segmenata", flush=True)

    print("[02] Ucitavam brojace", flush=True)
    counters_df = pd.read_csv(INTERMEDIATE_DIR / "counters_locations.csv", dtype={"counter_id": str})
    valid = counters_df.dropna(subset=["lat", "lon"]).copy()
    print(f"     {len(counters_df)} ukupno, {len(valid)} s GPS-om", flush=True)

    counters_gdf = gpd.GeoDataFrame(
        valid,
        geometry=gpd.points_from_xy(valid["lon"], valid["lat"]),
        crs=f"EPSG:{CRS_WGS84}",
    ).to_crs(epsg=CRS_HR)

    print("[02] Spajam po oznaci ceste", flush=True)
    by_name = counters_gdf.merge(
        segs[["oznaka_ceste", "kategorija_full", "geometry", "seg_id", "seg_length_m"]],
        on="oznaka_ceste", how="left", suffixes=("", "_road"),
    )

    def _dist(row):
        gr = row.get("geometry_road")
        if gr is None:
            return None
        try:
            if hasattr(gr, "is_empty") and gr.is_empty:
                return None
            return row.geometry.distance(gr)
        except Exception:
            return None

    by_name["dist_m"] = by_name.apply(_dist, axis=1)
    by_name = by_name.dropna(subset=["geometry_road"]).copy()

    if len(by_name):
        idx_best = by_name.groupby("counter_id")["dist_m"].idxmin()
        best_by_name = by_name.loc[idx_best].copy()
        best_by_name["match_method"] = "exact_road_name"
    else:
        best_by_name = pd.DataFrame()

    matched_ids = set(best_by_name["counter_id"]) if len(best_by_name) else set()

    leftover = counters_gdf[~counters_gdf["counter_id"].isin(matched_ids)].copy()
    print(f"[02] Fallback nearest za {len(leftover)} brojaca", flush=True)
    nearest_records = []
    if len(leftover):
        sindex = segs.sindex
        for _, row in leftover.iterrows():
            pt = row.geometry
            possible = list(sindex.query(pt.buffer(MAX_NEAREST_M * 4)))
            if not possible:
                possible = list(sindex.query(pt.buffer(MAX_NEAREST_M * 20)))
            if not possible:
                d_row = {k: v for k, v in row.to_dict().items() if k != "geometry"}
                d_row["match_method"] = "no_match"
                d_row["dist_m"] = None
                nearest_records.append(d_row)
                continue
            sub = segs.iloc[possible]
            distances = sub.geometry.distance(pt)
            best_idx = distances.idxmin()
            best = sub.loc[best_idx]
            d = distances.loc[best_idx]
            d_row = {k: v for k, v in row.to_dict().items() if k != "geometry"}
            d_row.update({
                "match_method": "spatial_nearest" if d <= MAX_NEAREST_M else "spatial_far",
                "dist_m": float(d),
                "matched_oznaka_ceste": best["oznaka_ceste"],
                "matched_kategorija": best["kategorija_full"],
                "seg_id": int(best["seg_id"]),
                "seg_length_m": float(best["seg_length_m"]),
            })
            nearest_records.append(d_row)

    nearest_df = pd.DataFrame(nearest_records)

    if len(best_by_name):
        best_by_name = best_by_name.rename(columns={"oznaka_ceste": "matched_oznaka_ceste"})
        best_by_name["oznaka_ceste"] = best_by_name["matched_oznaka_ceste"]
        out_a = best_by_name.drop(columns=["geometry", "geometry_road"], errors="ignore")
    else:
        out_a = pd.DataFrame()

    matched = pd.concat([out_a, nearest_df], ignore_index=True)

    def _conf(r):
        m = r.get("match_method")
        d = r.get("dist_m")
        if m == "exact_road_name" and d is not None and d <= 30:
            return "high"
        if m == "exact_road_name" and d is not None and d <= 100:
            return "medium"
        if m == "exact_road_name":
            return "low"
        if m == "spatial_nearest":
            return "low"
        return "none"

    matched["confidence"] = matched.apply(_conf, axis=1)

    cols_out = ["counter_id", "category", "oznaka_ceste", "naziv", "od", "do",
                "length_km", "lat", "lon", "matched_oznaka_ceste", "kategorija_full",
                "seg_id", "dist_m", "match_method", "confidence"]
    for c in cols_out:
        if c not in matched.columns:
            matched[c] = None
    matched[cols_out].to_csv(INTERMEDIATE_DIR / "counters_matched.csv", index=False)
    print(f"[02] counters_matched.csv ({len(matched)})", flush=True)
    print(matched.groupby("match_method").size().to_string(), flush=True)
    print(matched.groupby("confidence").size().to_string(), flush=True)

    out_segs = segs[["seg_id", "oznaka_ceste", "kategorija_full", "opis_ceste",
                     "seg_length_m", "geometry"]].copy()
    seg_path = INTERMEDIATE_DIR / "network_segments.parquet"
    if seg_path.exists():
        try:
            seg_path.unlink()
        except Exception:
            pass
    out_segs.to_parquet(seg_path)
    print(f"[02] network_segments.parquet ({len(out_segs)})", flush=True)

    bad_mask = matched["match_method"].isin(["no_match", "spatial_far"]) | (
        (matched["match_method"] == "exact_road_name") & (matched["dist_m"].fillna(0) > MAX_NEAREST_M)
    )
    bad = matched[bad_mask].copy()
    bad_path = INTERMEDIATE_DIR / "unmatched_counters.geojson"
    if len(bad):
        # Pisemo u /tmp pa kopiramo, da izbjegnemo "Operation not permitted"
        # ako fajl postoji u user-mounted folderu i ne moze se obrisati.
        import shutil, tempfile
        bad_gdf = gpd.GeoDataFrame(
            bad,
            geometry=gpd.points_from_xy(bad["lon"], bad["lat"]),
            crs=f"EPSG:{CRS_WGS84}",
        )
        tmp_path = Path(tempfile.gettempdir()) / "_unmatched_counters.geojson"
        if tmp_path.exists():
            tmp_path.unlink()
        bad_gdf.to_file(tmp_path, driver="GeoJSON")
        try:
            shutil.copyfile(tmp_path, bad_path)
        except Exception as e:
            print(f"[02] copyfile fail (probably already up to date): {e}", flush=True)
        print(f"[02] unmatched_counters.geojson ({len(bad)})", flush=True)
    else:
        print("[02] Nema unmatched brojaca", flush=True)

    print("[02] OK", flush=True)


if __name__ == "__main__":
    main()
