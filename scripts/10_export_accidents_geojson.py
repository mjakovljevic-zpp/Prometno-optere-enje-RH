"""10 - Izvoz nesreca u GeoJSON za web kartu (po godini)."""
import sys, shutil
from pathlib import Path
import pandas as pd
import json

PROJECT_ROOT = Path("/sessions/lucid-zealous-archimedes/mnt/HC_brojanje/karta-opterecenja")
PN_DIR = Path("/sessions/lucid-zealous-archimedes/mnt/HC_brojanje/PN/with_pgdp_pldp")
OUT_DIR = PROJECT_ROOT / "data" / "nesrece"
OUT_DIR.mkdir(parents=True, exist_ok=True)

POSLJ_MAP = {
    "PN s poginulim osobama": "P",
    "PN s teško ozlijeđenim osobama": "T",
    "PN s lakše ozlijeđenim osobama": "L",
    "PN s mat. štetom": "M",
}


def short_posljedica(s):
    if pd.isna(s): return None
    s = str(s).strip()
    for k, v in POSLJ_MAP.items():
        if k.lower() in s.lower():
            return v
    if "pogin" in s.lower(): return "P"
    if "tešk" in s.lower() or "tesk" in s.lower(): return "T"
    if "laks" in s.lower() or "lakš" in s.lower(): return "L"
    if "mater" in s.lower() or "mat" in s.lower(): return "M"
    return s[:1]


def main(yr):
    fp = PN_DIR / f"PN_{yr}_s_pgdp_pldp.csv"
    if not fp.exists():
        print(f"Nedostaje {fp}"); return
    print(f"[10] {yr}: {fp.name}", flush=True)
    df = pd.read_csv(fp, dtype=str)
    df["_lat"] = pd.to_numeric(df.get("GEO_SIRINA", df.get("GEOGRAFSKA ŠIRINA")), errors="coerce")
    df["_lon"] = pd.to_numeric(df.get("GEO_DUZINA", df.get("GEOGRAFSKA DUŽINA")), errors="coerce")
    df = df.dropna(subset=["_lat", "_lon"]).copy()
    print(f"     {len(df)} s GPS", flush=True)

    feats = []
    for _, r in df.iterrows():
        props = {
            "p": short_posljedica(r.get("POSLJ_PN")),  # posljedica
            "v": r.get("VRSTA_PN"),                    # vrsta
            "d": r.get("DATUM_NEZGODE"),              # datum
            "n": r.get("U_VAN_NASELJA"),              # u/van naselja
            "c": r.get("CESTA"),                       # MUP cesta
            "oz": r.get("OZNAKA_CESTE"),              # oznaka iz pipelinea
            "kat": r.get("KATEGORIJA"),                # kategorija
            "pgdp": r.get("PGDP"),
            "pldp": r.get("PLDP"),
            "rt": r.get("RAZINA_TOCNOSTI"),           # razina tocnosti
            "br": r.get("BROJAC_ID"),
            "mm": r.get("MATCH_METHOD"),
            "ulica": r.get("ULICA1"),
            "mjesto": r.get("MJESTO_PN"),
            "id": r.get("BROJ_PN"),
        }
        # Ukloni None, "nan"
        props = {k: v for k, v in props.items() if v is not None and str(v).lower() != "nan" and str(v) != ""}
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(r["_lon"], 6), round(r["_lat"], 6)]},
            "properties": props,
        })

    fc = {"type": "FeatureCollection", "features": feats}
    out_tmp = Path("/tmp") / f"nesrece_{yr}.geojson"
    with open(out_tmp, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    out_final = OUT_DIR / f"nesrece_{yr}.geojson"
    shutil.copyfile(out_tmp, out_final)
    print(f"     {out_final.name}: {out_final.stat().st_size//1024} kB", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]))
