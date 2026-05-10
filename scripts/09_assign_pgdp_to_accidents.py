"""09v9 - AC: brojaci dobivaju INTERVAL na liniji autoceste, nesreca pada u interval.

Logika za AC:
1. Za svaki AC brojac, parse section_desc 'cv. X - cv. Y'
2. Pronadji X i Y u OSM junctions po imenu -> izracunaj njihove m1 i m2
3. Brojac pokriva interval [min(m1,m2), max(m1,m2)] na liniji AC
4. Za nesrecu, izracunaj njenu mjeru m_acc na AC
5. Pronadji sve brojace cije intervali sadrze m_acc -> prosjek smjerova
6. Ako nijedan -> najblizi po mjeri
"""
import sys, shutil, math, unicodedata, pickle
from pathlib import Path
import pandas as pd
import geopandas as gpd
import shapely.wkb

PROJECT_ROOT = Path("/sessions/lucid-zealous-archimedes/mnt/HC_brojanje/karta-opterecenja")
PN_DIR = Path("/sessions/lucid-zealous-archimedes/mnt/HC_brojanje/PN")
OUT_DIR = PN_DIR / "with_pgdp_pldp"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SECTIONS_GJ = PROJECT_ROOT / "data" / "sections.geojson"
OSM_JUNCT = PROJECT_ROOT / "data" / "intermediate" / "osm_junctions.geojson"
TRAFFIC_LONG = PROJECT_ROOT / "data" / "intermediate" / "traffic_long.csv"
COUNTERS_MATCHED = PROJECT_ROOT / "data" / "intermediate" / "counters_matched.csv"
XINGS_PKL = PROJECT_ROOT / "data" / "intermediate" / "road_crossings.pkl"

CRS_HR = 3765; CRS_WGS84 = 4326

YEAR_FILES = {
    2021: ("PN_NESRECE_G2021.xlsx", "PN_NEZGODE_G2021"),
    2022: ("Podaci PN_2022_MUP.xlsx", "NEZGODE"),
    2023: ("PN_NESRECE_G2023.xlsx", "Sheet1"),
    2024: ("PN_NESRECE-SUDIONICI-VOZILA_G2024.xlsx", "PN_NESRECE_G2024"),
    2025: ("PN_NESRECE_G2025.xlsx", "Sheet1"),
}
GEO_COLS = {
    2021: ("GEOGRAFSKA ŠIRINA", "GEOGRAFSKA DUŽINA"),
    2022: ("GEO_SIRINA", "GEO_DUZINA"),
    2023: ("GEO_SIRINA", "GEO_DUZINA"),
    2024: ("GEO_SIRINA", "GEO_DUZINA"),
    2025: ("GEO_SIRINA", "GEO_DUZINA"),
}


def kategorija_for(road):
    if not road: return None
    if road.startswith("A"): return "autocesta"
    if road.startswith("DC"): return "državna cesta"
    if road.startswith("ŽC"): return "županijska cesta"
    if road.startswith("LC"): return "lokalna cesta"
    return None


def normalize_cesta(s):
    if s is None or pd.isna(s): return None
    s = str(s).strip()
    if not s: return None
    if s in ("L99999",): return None
    for full in ("DC", "AC", "ŽC", "LC"):
        if s.startswith(full): return s
    if s.startswith("ZC"): return "ŽC" + s[2:]
    if s[0] == "A": return s
    if s[0] == "D": return "DC" + s[1:]
    if s[0] in ("Ž", "Z"): return "ŽC" + s[1:]
    if s[0] == "L": return "LC" + s[1:]
    return None


def normalize_name(s):
    if s is None or pd.isna(s): return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    # Skin "cv." prefix
    s = s.replace("cv.", "").replace("c.", "").strip()
    return s


def parse_section_desc_ac(s):
    """'cv. Lucko - cv. Zdencina' -> ('lucko', 'zdencina')."""
    if pd.isna(s) or not s: return None, None
    parts = str(s).split(" - ")
    if len(parts) != 2: return None, None
    return normalize_name(parts[0]), normalize_name(parts[1])


def conf_combined(d_along_m, score):
    if d_along_m is None or score is None: return "none"
    if d_along_m <= 500 and score == 0: return "high"
    if d_along_m <= 1500 and score <= 0.3: return "high"
    if d_along_m <= 1000 and score <= 0.7: return "medium"
    if d_along_m <= 3000 and score <= 0.5: return "medium"
    if d_along_m <= 3000 and score <= 1.5: return "low"
    if d_along_m <= 8000 and score <= 1.0: return "low"
    return "estimate_range"


def main(yr):
    fname, sheet = YEAR_FILES[yr]
    fp = PN_DIR / str(yr) / fname
    print(f"[09v9] {yr}", flush=True)
    df = pd.read_excel(fp, sheet_name=sheet)
    print(f"     {len(df)} nesreca", flush=True)

    lat_c, lon_c = GEO_COLS[yr]
    df["_lat"] = pd.to_numeric(df[lat_c], errors="coerce")
    df["_lon"] = pd.to_numeric(df[lon_c], errors="coerce")
    df["_cesta_norm"] = df["CESTA"].map(normalize_cesta)

    print("     Loading caches...", flush=True)
    with open(XINGS_PKL, "rb") as f:
        xc = pickle.load(f)
    crossings = xc["crossings"]
    road_geom = {road: shapely.wkb.loads(wkb) for road, wkb in xc["road_geom_wkb"].items()}

    sections = gpd.read_file(SECTIONS_GJ).to_crs(epsg=CRS_HR)
    traffic = pd.read_csv(TRAFFIC_LONG, dtype={"counter_id": str})
    target_yr = yr if yr in (2021, 2022, 2023, 2024) else 2024
    col_pg = f"pgdp_{target_yr}"; col_pl = f"pldp_{target_yr}"

    osm_j = gpd.read_file(OSM_JUNCT).to_crs(epsg=CRS_HR) if OSM_JUNCT.exists() else None

    cm = pd.read_csv(COUNTERS_MATCHED, dtype={"counter_id": str})
    cnt_pts = {}
    for _, row in cm.iterrows():
        if pd.notna(row.get("lat")) and pd.notna(row.get("lon")):
            pt = gpd.GeoSeries([gpd.points_from_xy([row["lon"]], [row["lat"]])[0]],
                              crs=f"EPSG:{CRS_WGS84}").to_crs(epsg=CRS_HR).iloc[0]
            cnt_pts[row["counter_id"]] = pt

    counters_year = traffic[traffic["year"] == target_yr]
    cby_road = {}
    for _, r in counters_year.iterrows():
        road = r.get("oznaka_ceste")
        if not road or pd.isna(road): continue
        cby_road.setdefault(road, []).append(r.to_dict())

    def measure_on(road, point):
        g = road_geom.get(road)
        if g is None: return None
        try: return g.project(point)
        except: return None

    # OSM cvorovi po AC: dict ime_norm -> measure
    osm_per_road = {}      # road -> [{m, name_norm}]
    osm_name_lookup = {}   # road -> {name_norm: m}
    if osm_j is not None:
        for road, geom in road_geom.items():
            if not road.startswith("A"): continue
            buf = geom.buffer(200)
            cand = osm_j[osm_j.geometry.within(buf)]
            jl = []
            lookup = {}
            for _, j in cand.iterrows():
                m = measure_on(road, j.geometry)
                if m is None or pd.isna(j.get("name")): continue
                nn = normalize_name(j["name"])
                jl.append({"m": m, "name_norm": nn, "name_raw": j["name"]})
                if nn not in lookup or abs(m - jl[-1]["m"]) < 1:
                    lookup[nn] = m
            jl.sort(key=lambda x: x["m"])
            osm_per_road[road] = jl
            osm_name_lookup[road] = lookup

    # Brojaci na DC/ŽC/LC s GPS-om (za standardni score+dist)
    rcm = {}
    for road, lst in cby_road.items():
        for r in lst:
            cid = r["counter_id"]
            pt = cnt_pts.get(cid)
            if pt is None: continue
            m = measure_on(road, pt)
            if m is None: continue
            rcm.setdefault(road, []).append({**r, "m": m, "pt": pt})

    # AC brojaci -> izracunaj interval [m_lo, m_hi] svakog brojaca na svojoj cesti
    ac_brojaci = {}  # road -> list of {counter_id, pgdp, pldp, smjer, m_lo, m_hi, ime_section}
    for road, lst in cby_road.items():
        if not road.startswith("A"): continue
        lookup = osm_name_lookup.get(road, {})
        for r in lst:
            sd = r.get("section_desc")
            if not sd or pd.isna(sd): continue
            n1, n2 = parse_section_desc_ac(sd)
            if not n1 or not n2: continue
            # Probaj direktno ili fuzzy lookup
            m1 = lookup.get(n1)
            m2 = lookup.get(n2)
            # Fuzzy: try substring
            if m1 is None:
                for k, v in lookup.items():
                    if n1 and (n1 in k or k in n1): m1 = v; break
            if m2 is None:
                for k, v in lookup.items():
                    if n2 and (n2 in k or k in n2): m2 = v; break
            if m1 is None or m2 is None: continue
            ac_brojaci.setdefault(road, []).append({
                **r,
                "m_lo": min(m1, m2), "m_hi": max(m1, m2),
                "ime_section": sd,
            })

    print("     AC brojaci s validnim intervalima:", {r: len(v) for r, v in ac_brojaci.items()}, flush=True)

    # Statistike po cesti (fallback)
    road_stats = {}
    sec_full = sections[sections[col_pg].notna()].copy()
    for road, sub in sec_full.groupby("oznaka_ceste"):
        pg = sub[col_pg].dropna().tolist()
        pl = sub[col_pl].dropna().tolist()
        road_stats[road] = {
            "pgdp_min": min(pg) if pg else None, "pgdp_max": max(pg) if pg else None,
            "pgdp_avg": sum(pg) / len(pg) if pg else None,
            "pldp_min": min(pl) if pl else None, "pldp_max": max(pl) if pl else None,
            "pldp_avg": sum(pl) / len(pl) if pl else None,
        }

    def score_between(road, m1, m2):
        xings = crossings.get(road, [])
        if not xings: return 0.0, 0, 0
        lo, hi = (m1, m2) if m1 <= m2 else (m2, m1)
        s = 0.0; n = 0; nb = 0
        for m, w, _ in xings:
            if lo < m < hi: s += w; n += 1
            if lo < m < hi and w >= 0.7: nb += 1
        return s, n, nb

    out = df.copy()
    for c in ["PGDP", "PLDP", "PGDP_MIN", "PGDP_MAX", "PLDP_MIN", "PLDP_MAX",
              "OZNAKA_CESTE", "KATEGORIJA", "BROJAC_ID", "BROJAC_DIST_M",
              "BROJAC_DIST_UZ_CESTU_M", "BROJAC_SCORE", "BROJAC_RASKRIZJA_BROJ",
              "BROJAC_VAZNA_RASKRIZJA", "MATCH_METHOD", "AC_SECTION", "AC_SECTION_MATCH"]:
        out[c] = pd.NA
    out["RAZINA_TOCNOSTI"] = "none"

    valid_gps = df["_lat"].notna() & df["_lon"].notna()
    has_cesta = df["_cesta_norm"].notna()
    target_idx = df.loc[valid_gps & has_cesta].index.tolist()
    print(f"     S CESTA + GPS: {len(target_idx)}", flush=True)

    pts_geo = gpd.GeoSeries(
        gpd.points_from_xy(df.loc[target_idx, "_lon"], df.loc[target_idx, "_lat"]),
        crs=f"EPSG:{CRS_WGS84}", index=target_idx,
    ).to_crs(epsg=CRS_HR)

    nh = nm = nl = ne = nn = 0
    print("     Procesiram...", flush=True)

    for cnt_i, idx in enumerate(target_idx):
        if cnt_i > 0 and cnt_i % 2000 == 0:
            print(f"       {cnt_i}/{len(target_idx)}", flush=True)
        pt = pts_geo[idx]
        road = df.at[idx, "_cesta_norm"]
        kat = kategorija_for(road)

        out.at[idx, "OZNAKA_CESTE"] = road
        out.at[idx, "KATEGORIJA"] = kat

        if road not in road_geom:
            out.at[idx, "MATCH_METHOD"] = "road_not_in_network"
            nn += 1
            continue

        is_ac = road.startswith("A")
        m_acc = measure_on(road, pt)
        if m_acc is None:
            out.at[idx, "MATCH_METHOD"] = "no_data"; nn += 1; continue

        if is_ac:
            # Identificiraj AC sekciju iz GPS-a
            jl = osm_per_road.get(road, [])
            ac_section = None
            if jl:
                before = [j for j in jl if j["m"] <= m_acc]
                after = [j for j in jl if j["m"] >= m_acc]
                jp = max(before, key=lambda x: x["m"]) if before else None
                jn = min(after, key=lambda x: x["m"]) if after else None
                if jp and jn:
                    ac_section = f"čv. {jp['name_raw']} - čv. {jn['name_raw']}"
            out.at[idx, "AC_SECTION"] = ac_section

            # Pronadji brojace cije intervale [m_lo, m_hi] sadrze m_acc
            lst = ac_brojaci.get(road, [])
            in_interval = [b for b in lst if b["m_lo"] <= m_acc <= b["m_hi"]]
            if in_interval:
                # Pravi match - prosjek smjerova
                pgs = [b["pgdp"] for b in in_interval if pd.notna(b.get("pgdp"))]
                pls = [b["pldp"] for b in in_interval if pd.notna(b.get("pldp"))]
                cls = "high" if len(in_interval) >= 2 else "medium"
                if pgs: out.at[idx, "PGDP"] = int(sum(pgs) / len(pgs))
                if pls: out.at[idx, "PLDP"] = int(sum(pls) / len(pls))
                out.at[idx, "BROJAC_ID"] = ";".join(str(b["counter_id"]) for b in in_interval)
                out.at[idx, "BROJAC_SCORE"] = 0.0
                out.at[idx, "AC_SECTION_MATCH"] = "match"
                out.at[idx, "RAZINA_TOCNOSTI"] = cls
                out.at[idx, "MATCH_METHOD"] = "ac_section_avg"
                if cls == "high": nh += 1
                else: nm += 1
                continue
            elif lst:
                # Najblizi po sredini intervala
                best = min(lst, key=lambda b: min(abs(m_acc - b["m_lo"]), abs(m_acc - b["m_hi"])))
                d_along = min(abs(m_acc - best["m_lo"]), abs(m_acc - best["m_hi"]))
                cls = "low" if d_along < 5000 else "estimate_range"
                if cls == "estimate_range":
                    # raspon svih
                    pgs_all = [b["pgdp"] for b in lst if pd.notna(b.get("pgdp"))]
                    pls_all = [b["pldp"] for b in lst if pd.notna(b.get("pldp"))]
                    if pgs_all:
                        out.at[idx, "PGDP"] = int(sum(pgs_all) / len(pgs_all))
                        out.at[idx, "PGDP_MIN"] = int(min(pgs_all))
                        out.at[idx, "PGDP_MAX"] = int(max(pgs_all))
                    if pls_all:
                        out.at[idx, "PLDP"] = int(sum(pls_all) / len(pls_all))
                        out.at[idx, "PLDP_MIN"] = int(min(pls_all))
                        out.at[idx, "PLDP_MAX"] = int(max(pls_all))
                    out.at[idx, "MATCH_METHOD"] = "ac_road_avg"
                    out.at[idx, "RAZINA_TOCNOSTI"] = "estimate_range"
                    out.at[idx, "AC_SECTION_MATCH"] = "no_match_far"
                    ne += 1
                else:
                    out.at[idx, "PGDP"] = best["pgdp"] if pd.notna(best.get("pgdp")) else None
                    out.at[idx, "PLDP"] = best["pldp"] if pd.notna(best.get("pldp")) else None
                    out.at[idx, "BROJAC_ID"] = best["counter_id"]
                    out.at[idx, "BROJAC_DIST_UZ_CESTU_M"] = d_along
                    out.at[idx, "AC_SECTION_MATCH"] = "no_match_near"
                    out.at[idx, "MATCH_METHOD"] = "ac_nearest_section"
                    out.at[idx, "RAZINA_TOCNOSTI"] = "low"
                    nl += 1
                continue
            else:
                # Fallback - prosjek svih AC brojaca na cesti (cak i bez intervala)
                all_ac = cby_road.get(road, [])
                pgs_all = [b["pgdp"] for b in all_ac if pd.notna(b.get("pgdp"))]
                pls_all = [b["pldp"] for b in all_ac if pd.notna(b.get("pldp"))]
                if pgs_all:
                    out.at[idx, "PGDP"] = int(sum(pgs_all) / len(pgs_all))
                    out.at[idx, "PGDP_MIN"] = int(min(pgs_all))
                    out.at[idx, "PGDP_MAX"] = int(max(pgs_all))
                if pls_all:
                    out.at[idx, "PLDP"] = int(sum(pls_all) / len(pls_all))
                    out.at[idx, "PLDP_MIN"] = int(min(pls_all))
                    out.at[idx, "PLDP_MAX"] = int(max(pls_all))
                out.at[idx, "MATCH_METHOD"] = "ac_road_avg"
                out.at[idx, "RAZINA_TOCNOSTI"] = "estimate_range"
                ne += 1
                continue

        # DC/ŽC/LC standardno
        cms = rcm.get(road, [])
        if not cms:
            rs = road_stats.get(road)
            if rs and rs["pgdp_avg"] is not None:
                out.at[idx, "PGDP"] = int(rs["pgdp_avg"])
                out.at[idx, "PGDP_MIN"] = int(rs["pgdp_min"])
                out.at[idx, "PGDP_MAX"] = int(rs["pgdp_max"])
                if rs["pldp_avg"]:
                    out.at[idx, "PLDP"] = int(rs["pldp_avg"])
                    out.at[idx, "PLDP_MIN"] = int(rs["pldp_min"])
                    out.at[idx, "PLDP_MAX"] = int(rs["pldp_max"])
                out.at[idx, "MATCH_METHOD"] = "same_road_estimate"
                out.at[idx, "RAZINA_TOCNOSTI"] = "estimate_range"
            else:
                out.at[idx, "MATCH_METHOD"] = "no_counter_on_road"
            ne += 1
            continue

        candidates = []
        for c in cms:
            s, xn, xb = score_between(road, m_acc, c["m"])
            d_along = abs(m_acc - c["m"])
            try: dc = pt.distance(c["pt"])
            except: dc = None
            candidates.append({"c": c, "s": s, "xn": xn, "xb": xb, "d_along": d_along, "d_phys": dc})
        candidates.sort(key=lambda x: (x["s"], x["d_along"]))
        best = candidates[0]
        cnt = best["c"]
        cls = conf_combined(best["d_along"], best["s"])
        out.at[idx, "PGDP"] = cnt["pgdp"] if pd.notna(cnt.get("pgdp")) else None
        out.at[idx, "PLDP"] = cnt["pldp"] if pd.notna(cnt.get("pldp")) else None
        out.at[idx, "BROJAC_ID"] = cnt["counter_id"]
        out.at[idx, "BROJAC_DIST_M"] = best["d_phys"]
        out.at[idx, "BROJAC_DIST_UZ_CESTU_M"] = best["d_along"]
        out.at[idx, "BROJAC_SCORE"] = round(best["s"], 3)
        out.at[idx, "BROJAC_RASKRIZJA_BROJ"] = best["xn"]
        out.at[idx, "BROJAC_VAZNA_RASKRIZJA"] = best["xb"]
        if cls == "estimate_range":
            rs = road_stats.get(road)
            if rs and rs["pgdp_avg"] is not None:
                out.at[idx, "PGDP_MIN"] = int(rs["pgdp_min"])
                out.at[idx, "PGDP_MAX"] = int(rs["pgdp_max"])
                out.at[idx, "PGDP"] = int(rs["pgdp_avg"])
                if rs["pldp_avg"]:
                    out.at[idx, "PLDP_MIN"] = int(rs["pldp_min"])
                    out.at[idx, "PLDP_MAX"] = int(rs["pldp_max"])
                    out.at[idx, "PLDP"] = int(rs["pldp_avg"])
        out.at[idx, "RAZINA_TOCNOSTI"] = cls
        out.at[idx, "MATCH_METHOD"] = "dist_score"
        if cls == "high": nh += 1
        elif cls == "medium": nm += 1
        elif cls == "low": nl += 1
        else: ne += 1

    print(f"     h={nh} m={nm} l={nl} estimate={ne} none={nn}", flush=True)

    out_clean = out.drop(columns=[c for c in ["_lat", "_lon", "_cesta_norm"] if c in out.columns])
    csv_tmp = Path("/tmp") / f"PN_{yr}_v9.csv"
    out_clean.to_csv(csv_tmp, index=False, encoding="utf-8-sig")
    csv_final = OUT_DIR / f"PN_{yr}_s_pgdp_pldp.csv"
    shutil.copyfile(csv_tmp, csv_final)
    print(f"     CSV: {csv_final.name}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]))
