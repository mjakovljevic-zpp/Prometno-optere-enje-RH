"""01 - Ucitavanje i ciscenje ulaznih podataka.

Ulaz: HC_brojanje/Podaci o lokacijama brojaca.xls
      HC_brojanje/Opterecenja/<godina>/Promet_na_cestama_*.xls

Izlaz: data/intermediate/{counters_locations.csv, traffic_long.csv, data_quality.json}
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
RAW_ROOT = PROJECT_ROOT.parent
LOCATIONS_XLS = RAW_ROOT / "Podaci o lokacijama brojaca.xls"
TRAFFIC_DIR = RAW_ROOT / "Opterecenja"
DATA_DIR = PROJECT_ROOT / "data"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
YEARS = [2021, 2022, 2023, 2024]
CATEGORY_PREFIX = {"DC": "DC", "AC": "AC", "ZC": "ŽC", "LC": "LC"}
REF_PREFIX_MAP = {"D": "DC", "A": "AC", "Ž": "ŽC", "L": "LC"}


def to_int_or_nan(value):
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return int(value) if not pd.isna(value) else None
    s = str(value).strip()
    if not s or set(s) <= {".", " "}:
        return None
    s = s.replace("\xa0", "").replace(" ", "").replace(",", "")
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def norm_counter_code(value):
    if pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def norm_road_number(value):
    if pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_ref_code(value):
    if pd.isna(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    for full in ("DC", "AC", "ŽC", "LC"):
        if s.startswith(full):
            return s
    if s[0] in REF_PREFIX_MAP:
        rest = s[1:]
        if re.match(r"^[0-9A-Za-z\.]+$", rest):
            return REF_PREFIX_MAP[s[0]] + rest
    return s


def build_full_road_code(category, road_number):
    if not road_number:
        return None
    if any(road_number.startswith(p) for p in ("DC", "AC", "ŽC", "LC")):
        return road_number
    if category == "AC" and road_number.startswith("A"):
        return "AC" + road_number[1:]
    prefix = CATEGORY_PREFIX.get(category)
    if not prefix:
        return None
    return f"{prefix}{road_number}"


def parse_ac_section_text(text):
    if pd.isna(text):
        return None, None
    s = str(text).strip()
    if not s:
        return None, None
    parts = re.split(r"\s+[-–]\s+", s, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return s, None


def parse_promet_sheet(filepath, sheet, year, category):
    raw = pd.read_excel(filepath, sheet_name=sheet, header=None)
    valid_mask = pd.to_numeric(raw[1], errors="coerce").notna()
    df = raw.loc[valid_mask].copy().reset_index(drop=True)
    if df.empty:
        return df
    is_ac_short = df.shape[1] == 8
    if is_ac_short:
        ods, dos = zip(*df[6].map(parse_ac_section_text))
        out = pd.DataFrame({
            "year": year, "category": category,
            "road_number": df[0].map(norm_road_number),
            "counter_id": df[1].map(norm_counter_code),
            "naziv": df[2].astype(str).str.strip(),
            "pgdp": df[3].map(to_int_or_nan),
            "pldp": df[4].map(to_int_or_nan),
            "brojenje": df[5].astype(str).str.strip(),
            "od": [normalize_ref_code(x) for x in ods],
            "do": [normalize_ref_code(x) for x in dos],
            "length_km": pd.to_numeric(df[7], errors="coerce"),
            "section_desc": df[6].astype(str).str.strip(),
        })
    else:
        out = pd.DataFrame({
            "year": year, "category": category,
            "road_number": df[0].map(norm_road_number),
            "counter_id": df[1].map(norm_counter_code),
            "naziv": df[2].astype(str).str.strip(),
            "pgdp": df[3].map(to_int_or_nan),
            "pldp": df[4].map(to_int_or_nan),
            "brojenje": df[5].astype(str).str.strip(),
            "od": df[6].map(normalize_ref_code),
            "do": df[7].map(normalize_ref_code),
            "length_km": pd.to_numeric(df[8], errors="coerce"),
            "section_desc": df[6].astype(str).str.strip() + " - " + df[7].astype(str).str.strip(),
        })
    out["oznaka_ceste"] = [build_full_road_code(c, r) for c, r in zip(out["category"], out["road_number"])]
    out = out[out["counter_id"].notna()].reset_index(drop=True)
    return out


def parse_locations(filepath):
    df = pd.read_excel(filepath, sheet_name="Tablica", header=0)
    df = df.rename(columns={
        "Cesta": "road_number_loc", "Oznaka": "counter_id", "Naziv": "naziv_loc",
        "Od": "od_loc", "Do": "do_loc", "Duljina odsječka": "length_km_loc",
        "Zemlj. širina": "lat", "Zemlj. duljina": "lon",
    })
    df["counter_id"] = df["counter_id"].map(norm_counter_code)
    df["road_number_loc"] = df["road_number_loc"].map(norm_road_number)
    df["od_loc"] = df["od_loc"].map(normalize_ref_code)
    df["do_loc"] = df["do_loc"].map(normalize_ref_code)
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df[df["counter_id"].notna()].copy()
    return df[["counter_id", "road_number_loc", "naziv_loc", "od_loc", "do_loc",
               "length_km_loc", "lat", "lon"]]


def main():
    print(f"[01] Ucitavam lokacije: {LOCATIONS_XLS.name}", flush=True)
    locations = parse_locations(LOCATIONS_XLS)
    print(f"     -> {len(locations)} brojaca", flush=True)
    long_records = []
    quality = {"per_year_per_category": {}, "issues": []}
    for year in YEARS:
        ydir = TRAFFIC_DIR / str(year)
        candidates = sorted(ydir.glob(f"Promet_na_cestama_*_{year}.xls*"))
        if not candidates:
            quality["issues"].append(f"Nema datoteke za {year}")
            continue
        promet_fp = candidates[0]
        print(f"[01] {year}: {promet_fp.name}", flush=True)
        xl = pd.ExcelFile(promet_fp)
        for cat in ("DC", "AC", "ZC", "LC"):
            sheet = next((s for s in xl.sheet_names if s.upper().startswith(cat) and str(year) in s), None)
            if not sheet:
                quality["issues"].append(f"Nema sheeta {cat} za {year}")
                continue
            df = parse_promet_sheet(promet_fp, sheet, year, cat)
            long_records.append(df)
            quality["per_year_per_category"].setdefault(year, {})[cat] = len(df)
            print(f"     {cat}: {len(df)}", flush=True)
    traffic = pd.concat(long_records, ignore_index=True)
    print(f"[01] traffic shape: {traffic.shape}", flush=True)
    dup_mask = traffic.duplicated(subset=["year", "counter_id"], keep=False)
    if bool(dup_mask.any()):
        quality["issues"].append(f"{int(dup_mask.sum())} duplikata")
        traffic = traffic.drop_duplicates(subset=["year", "counter_id"], keep="first")
    merged = traffic.merge(locations, on="counter_id", how="left", indicator=True)
    no_loc = merged["_merge"] == "left_only"
    if bool(no_loc.any()):
        miss = sorted({str(x) for x in merged.loc[no_loc, "counter_id"].dropna()})
        quality["counters_without_gps"] = miss[:50]
        quality["counters_without_gps_count"] = len(miss)
    merged = merged.drop(columns=["_merge"])
    out_cols = ["year", "category", "oznaka_ceste", "road_number", "counter_id",
                "naziv", "pgdp", "pldp", "od", "do", "section_desc", "length_km",
                "brojenje", "lat", "lon", "od_loc", "do_loc", "length_km_loc", "naziv_loc"]
    for col in out_cols:
        if col not in merged.columns:
            merged[col] = None
    merged[out_cols].to_csv(INTERMEDIATE_DIR / "traffic_long.csv", index=False)
    last_year = traffic.sort_values("year").drop_duplicates(subset=["counter_id"], keep="last")
    locations_meta = last_year.merge(locations, on="counter_id", how="left")
    locations_meta[["counter_id", "category", "oznaka_ceste", "naziv", "od", "do",
                    "length_km", "lat", "lon"]].to_csv(
        INTERMEDIATE_DIR / "counters_locations.csv", index=False)
    quality["total_traffic_rows"] = int(len(merged))
    quality["unique_counters"] = int(merged["counter_id"].nunique())
    quality["years_loaded"] = sorted(merged["year"].unique().tolist())
    print(f"[01] Ukupno: {quality['total_traffic_rows']} redaka, {quality['unique_counters']} brojaca", flush=True)
    with open(INTERMEDIATE_DIR / "data_quality.json", "w", encoding="utf-8") as f:
        json.dump(quality, f, ensure_ascii=False, indent=2)
    print(f"[01] Spremljeno u: {INTERMEDIATE_DIR}", flush=True)


if __name__ == "__main__":
    main()
