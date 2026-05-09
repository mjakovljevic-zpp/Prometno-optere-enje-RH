"""Centralizirana konfiguracija putanja za pipeline.

Ovaj modul zna gdje se nalaze sirovi podaci (Brzine/Opterecenja/Mreza
cesta/lokacije brojača) i gdje pipeline upisuje svoje rezultate. Svi
ostali skripti uvoze ove putanje.
"""
from __future__ import annotations
from pathlib import Path

# Korijen projekta = mapa u kojoj je smješten ovaj scripts/ folder
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Sirovi podaci žive u roditeljskoj mapi (HC_brojanje/), izvan repozitorija
RAW_ROOT = PROJECT_ROOT.parent

LOCATIONS_XLS = RAW_ROOT / "Podaci o lokacijama brojaca.xls"
TRAFFIC_DIR = RAW_ROOT / "Opterecenja"
NETWORK_GPKG = RAW_ROOT / "Mreza cesta" / "20250625_091453_cesta.gpkg"

# Izlazni direktoriji
DATA_DIR = PROJECT_ROOT / "data"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
WEB_DATA_DIR = DATA_DIR  # GeoJSON za frontend
REPORTS_DIR = PROJECT_ROOT / "reports"
MANUAL_OVERRIDES_CSV = DATA_DIR / "manual_overrides.csv"

INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Godine za koje očekujemo podatke
YEARS = [2021, 2022, 2023, 2024]

# Mapiranje skraćenice kategorije → puni opis u GPKG-u
CATEGORY_FULL = {
    "DC": "državna cesta",
    "AC": "autocesta",
    "ZC": "županijska cesta",
    "LC": "lokalna cesta",
}

# Mapiranje skraćenice kategorije → prefiks oznake u GIS sloju
CATEGORY_PREFIX = {
    "DC": "DC",
    "AC": "AC",
    "ZC": "ŽC",
    "LC": "LC",
}

# Mapiranje znaka iz Od/Do polja → GIS prefiks
# (D207 → DC207; A2 → AC2; Ž2258 → ŽC2258; L22001 → LC22001)
REF_PREFIX_MAP = {
    "D": "DC",
    "A": "AC",
    "Ž": "ŽC",
    "L": "LC",
}

# Koordinatni sustavi
CRS_WGS84 = 4326
CRS_HR = 3765  # HTRS96 / Croatia TM, metrički

# Pragovi
MAX_COUNTER_TO_ROAD_M = 250.0  # metara — upozorenje ako je brojač dalji
SECTION_SEARCH_BUFFER_M = 200.0  # tolerancija pri traženju Od/Do raskrižja
