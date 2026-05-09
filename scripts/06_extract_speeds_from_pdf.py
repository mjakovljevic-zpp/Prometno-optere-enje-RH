"""06 - Ekstrakcija prosjecnih brzina iz Brzine PDF-ova (Tablica 2).

Ulaz: HC_brojanje/Brzine/Brzine <godina>.pdf
Izlaz: data/intermediate/speeds_long.csv

Format Tablice 2 u PDF-u:
  CESTA  brojac_id  ime ...  pocetak  kraj  v_max_dop  v1  v2  V85_1  V85_2

Primjer reda:
  DC30 2043 Petina (smjer Velika Gorica) A3 D30 90 84 84 97 100
"""
from __future__ import annotations
import re
from pathlib import Path
import pandas as pd
import pdfplumber

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
RAW_ROOT = PROJECT_ROOT.parent
BRZINE_DIR = RAW_ROOT / "Brzine"
INTERMEDIATE_DIR = PROJECT_ROOT / "data" / "intermediate"
INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

# Mapa godine -> PDF datoteka
PDF_MAP = {
    2021: BRZINE_DIR / "Brzine 2021.pdf",
    2022: BRZINE_DIR / "Brzine 2022.pdf",
    2023: BRZINE_DIR / "Brzine 2023.pdf",
}

ROAD_RE = re.compile(r"^(?:DC|AC|ŽC|LC|Ner|A|D|Ž|L|N)[A-Za-z]?\d+[A-Za-z]?$|^Ner$|^Ž?\d+$")
VAL_RE = re.compile(r"^\d+(?:\.\d+)?$")
MAXDOP_RE = re.compile(r"^\d+(?:/\d+)?$")


def is_road_token(t: str) -> bool:
    if t in ("Ner", "GP", "G.A.P.", "AP", "A.P."):
        return True
    return bool(ROAD_RE.match(t)) or bool(re.match(r"^[A-ZŽ]\d+", t))


def parse_line(line: str):
    """Parsiraj jedan redak Tablice 2.
    Vraca dict ili None ako redak nije podataka.
    """
    line = line.strip()
    if not line:
        return None
    # Header / page numbers / pojašnjenja kratica
    if any(k in line for k in (
        "MJERNO MJESTO", "ODSJEČAK", "OZNAKA", "Početak",
        "Pojašnjenje", "Tablica", "Naručitelj", "BRZINE VOZILA",
    )):
        return None

    tokens = line.split()
    if len(tokens) < 8:
        return None

    # Zadnji 5 (ili 4 ako neki nedostaje) trebaju biti brojevi
    nums = []
    while tokens and (VAL_RE.match(tokens[-1]) or MAXDOP_RE.match(tokens[-1])):
        nums.append(tokens.pop())
        if len(nums) >= 5:
            break
    if len(nums) < 5:
        return None
    nums.reverse()  # max_dop, v1, v2, V85_1, V85_2
    max_dop, v1, v2, V85_1, V85_2 = nums

    if len(tokens) < 4:
        return None

    # Pretposljednja dva tokena = pocetak, kraj (ali Ime moze sadržavati razmake)
    # Pristup: zadnje dva tokena su Početak/Kraj ako su "road-like"
    # Ali u nekim slučajevima Početak/Kraj može biti slobodan tekst (G.A.P., naselje)
    # Pa procijeni s regex-om: tokeni koji počinju velikim slovom + brojem.
    # Pojednostavljeno: zadnja dva tokena su pocetak/kraj.
    kraj = tokens.pop()
    pocetak = tokens.pop()

    if len(tokens) < 2:
        return None

    cesta = tokens[0]
    brojac = tokens[1]
    if not VAL_RE.match(brojac):
        return None
    ime = " ".join(tokens[2:]).strip()

    return {
        "cesta": cesta,
        "counter_id": brojac,
        "naziv": ime,
        "pocetak": pocetak,
        "kraj": kraj,
        "v_max_dop": max_dop,
        "v_avg_smjer1": float(v1),
        "v_avg_smjer2": float(v2),
        "v85_smjer1": float(V85_1),
        "v85_smjer2": float(V85_2),
    }


def extract_table2(pdf_path: Path, year: int):
    """Ekstrahiraj Tablica 2 iz PDF-a."""
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        in_table = False
        max_pages = min(len(pdf.pages), 25)
        for i in range(max_pages):
            text = pdf.pages[i].extract_text() or ""
            if "Mjerna mjesta s osnovnim brzinskim pokazateljima" in text:
                in_table = True
            if not in_table:
                continue
            for line in text.splitlines():
                rec = parse_line(line)
                if rec:
                    rec["year"] = year
                    rows.append(rec)
            # Tablica završava kad pojašnjenje kratica
            if "Pojašnjenje kratica" in text:
                in_table = False
                break
    return rows


def main():
    print("[06] Ekstrakcija brzina iz PDF-ova", flush=True)
    all_rows = []
    for year, fp in PDF_MAP.items():
        if not fp.exists():
            print(f"     Nedostaje {fp.name}", flush=True)
            continue
        print(f"     {year}: {fp.name}", flush=True)
        rows = extract_table2(fp, year)
        print(f"       -> {len(rows)} redaka", flush=True)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    if df.empty:
        print("[06] Nema podataka!", flush=True)
        return

    # Izračunaj prosječnu brzinu (oba smjera)
    df["v_avg"] = (df["v_avg_smjer1"] + df["v_avg_smjer2"]) / 2.0
    df["v85_avg"] = (df["v85_smjer1"] + df["v85_smjer2"]) / 2.0

    out = INTERMEDIATE_DIR / "speeds_long.csv"
    df.to_csv(out, index=False)
    print(f"[06] {len(df)} redaka u {out}", flush=True)
    print(df.groupby("year").size().to_string(), flush=True)
    print("[06] OK", flush=True)


if __name__ == "__main__":
    main()
