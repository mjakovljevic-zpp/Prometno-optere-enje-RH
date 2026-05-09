# Karta opterećenja cestovne mreže RH

Statička web aplikacija za interaktivni prikaz prosječnoga godišnjeg dnevnog
prometa (**PGDP**) i prosječnoga ljetnog dnevnog prometa (**PLDP**) po
cestovnim dionicama u Republici Hrvatskoj, za godine **2021. – 2024.**

Vizualni stil aplikacije slijedi stranicu *Evaluacija NPSCP 2021. – 2025.*
Dva različita izvora prometnih podataka – točke brojača (XLS publikacije
Hrvatskih cesta) i GIS sloj cestovne mreže (geoportal.hrvatske-ceste.hr) –
preprocesiraju se u pythonu, a zatim ih frontend (Leaflet + Chart.js) crta
kao linijsku kartu s pripisanim vrijednostima.

> **Napomena:** Aplikacija je u potpunosti **statička** i prikladna je za
> hosting na **GitHub Pages** bez ikakvog backenda.

---

## Sadržaj repozitorija

```
karta-opterecenja/
├── index.html                          # glavna stranica (karta)
├── assets/
│   ├── css/style.css                   # stilovi (slijedi NPSCP dizajn)
│   └── js/map.js                       # Leaflet logika, filteri, popup
├── data/
│   ├── sections.geojson                # generirano: dionice s PGDP/PLDP po godini
│   ├── counters.geojson                # generirano: točke brojača s GPS-om
│   ├── summary.json                    # generirano: agregati za dashboard
│   ├── manual_overrides.csv            # ručne korekcije (opcionalno)
│   └── intermediate/                   # međurezultati pipelinea
├── reports/
│   ├── quality_report.html             # generirano: izvještaj validacije
│   └── issues_*.csv                    # generirano: pojedini popisi problema
├── scripts/
│   ├── 01_load_clean_data.py
│   ├── 02_match_counters_to_network.py
│   ├── 03_assign_traffic_to_sections.py
│   ├── 04_export_web_data.py
│   ├── 05_quality_report.py
│   └── run_pipeline.py                 # orkestrator (sve u jednoj naredbi)
├── metodologija.md                     # detaljna metodologija dodjele
├── requirements.txt                    # Python ovisnosti
└── README.md                           # ovaj dokument
```

Sirovi podaci žive u **roditeljskoj mapi** (`HC_brojanje/`):

```
HC_brojanje/
├── Podaci o lokacijama brojaca.xls     # GPS koordinate brojača
├── Opterecenja/
│   ├── 2021/Promet_na_cestama_…2021.xls
│   ├── 2022/Promet_na_cestama_…2022.xls
│   ├── 2023/Promet_na_cestama_…2023.xls
│   └── 2024/Promet_na_cestama_…2024.xls
└── Mreza cesta/
    └── 20250625_091453_cesta.gpkg      # GIS sloj cesta (HTRS96/TM, EPSG:3765)
```

---

## Brzi početak

### 1) Instaliraj Python ovisnosti

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Pokreni pipeline (generira sve GeoJSON datoteke)

```bash
python scripts/run_pipeline.py
```

Pojedinačno:

```bash
python scripts/01_load_clean_data.py         # XLS → CSV (long format)
python scripts/02_match_counters_to_network.py  # Brojači ↔ GIS mreža
python scripts/03_assign_traffic_to_sections.py # Voronoi po cesti
python scripts/04_export_web_data.py         # GeoJSON za Leaflet
python scripts/05_quality_report.py          # HTML/CSV izvještaj
```

### 3) Lokalni preview

```bash
python -m http.server 8000
# otvori http://localhost:8000/
```

### 4) Objavi na GitHub Pages

1. Inicijaliziraj git i commit:
   ```bash
   git init -b main
   git add .
   git commit -m "Karta opterećenja – inicijalna verzija"
   git remote add origin <tvoj_repo_url>
   git push -u origin main
   ```
2. U postavkama repozitorija → **Pages**, izaberi:
   - Source: *Deploy from a branch*
   - Branch: `main` / `(root)`
3. Stranica će biti dostupna na
   `https://<korisnicko_ime>.github.io/<naziv_repoa>/`.

---

## Ulazni i izlazni podaci

### Ulazi

| Datoteka | Opis | Spojni ključ |
| --- | --- | --- |
| `Podaci o lokacijama brojaca.xls` | šifra brojača, naziv, lat/lon, opis dionice (Od/Do) | `Oznaka` (šifra brojača) |
| `Opterecenja/<godina>/Promet_na_cestama_*.xls` | PGDP/PLDP po brojaču (4 sheeta: DC, AC, ZC, LC) | `Brojačko mjesto Oznaka` |
| `Mreza cesta/20250625_091453_cesta.gpkg` | linijska geometrija cijele mreže (3 433 cesta) | `oznaka ceste` (npr. `DC1`) |

### Izlazi (web)

- `data/sections.geojson` — `LineString` segmenti pripadajuće ceste s godišnjim
  vrijednostima u **wide formatu** (`pgdp_2021`, `pldp_2021`, `conf_2021`, …).
- `data/counters.geojson` — točke brojača (s GPS-om) za dijagnostiku.
- `data/summary.json` — broj dionica, ukupna duljina, prosjek/maks PGDP/PLDP
  po godini i kategoriji.
- `reports/quality_report.html` — izvještaj validacije (otvori izravno u
  pregledniku).

---

## Kako frontend stilira kartu

Boja i debljina linije ovise o **PGDP** ili **PLDP** vrijednosti za izabranu
godinu. Paleta je sedmerostupanjska (svijetlo → tamna):

| Stupanj | Raspon | Boja |
| --- | --- | --- |
| 1 | ≤ 1 000 | `--t1` |
| 2 | ≤ 3 000 | `--t2` |
| 3 | ≤ 6 000 | `--t3` |
| 4 | ≤ 10 000 | `--t4` |
| 5 | ≤ 15 000 | `--t5` |
| 6 | ≤ 22 000 | `--t6` |
| 7 | > 22 000 | `--t7` |

Filteri (godina, kategorija ceste, raspon PGDP/PLDP, oznaka ceste, pouzdanost,
prikaz brojača, samo problematične dodjele) trenutno reagiraju na promjenu i
ažuriraju i mapu i sažetak.

Klikom na dionicu otvara se popup s godišnjim trendom (PGDP, PLDP) za sve
godine i meta-podatcima dionice.

---

## Poznata ograničenja

- **Brzine** (PDF datoteke u `Brzine/`) trenutno **nisu** uključene u
  aplikaciju – izvor je netekstualan PDF (mahom skenirane tablice) pa
  automatska ekstrakcija nije pouzdana. Pripremljena su mjesta u
  shemi i UI-u na koja je trivijalno dodati brzine kasnije.
- **313 brojača nema GPS koordinate** u službenoj tablici lokacija. Njima se
  vrijednost pripisuje **cijeloj cesti** (pouzdanost `low`) samo ako tu cestu
  ne pokriva drugi (geo-locirani) brojač.
- **Lokalne nerazvrstane ceste** (oznaka `LCner.` u brojačkoj tablici) ne
  postoje u GIS sloju cestovne mreže – te brojače aplikacija ne može prostorno
  povezati.
- Algoritam dodjele radi po **Voronoi-ju** (svaki segment pripada najbližem
  brojaču po linearnom mjerilu duž ceste). Ako u opisu dionice (`Od`/`Do`)
  postoji jasna referenca na drugu cestu koja se može prostorno locirati,
  tu informaciju koristimo, ali ne striktno; za ručno fino podešavanje
  dostupna je `data/manual_overrides.csv` (vidi
  [`metodologija.md`](metodologija.md)).

---

## Licenca i izvori

- Podatci o brojanju prometa © **Hrvatske ceste d.o.o.**, korišteni za potrebe
  evaluacije i vizualizacije.
- GIS sloj mreže cesta © **Hrvatske ceste**, dostupan kroz
  [geoportal.hrvatske-ceste.hr](https://geoportal.hrvatske-ceste.hr/gis).
- Pozadinska karta © OpenStreetMap suradnici.

Kod aplikacije objavljen je pod MIT licencom.
