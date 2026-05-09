# Metodologija dodjele prometnih opterećenja dionicama

Cilj ovog dokumenta je transparentno opisati kako se točkovne vrijednosti
brojača prometa **PGDP** (prosječni godišnji dnevni promet) i **PLDP**
(prosječni ljetni dnevni promet) prenose na **linijske dionice** službene
GIS mreže cesta Republike Hrvatske.

---

## 1. Ulazni podatci i ključevi

| Izvor | Sadrži | Ključ |
| --- | --- | --- |
| Tablica brojača (`Podaci o lokacijama brojaca.xls`) | šifra, naziv, lat/lon, `Od`/`Do` reference | `Oznaka` |
| Godišnji "Promet na cestama RH" XLS | PGDP/PLDP po brojaču po godini | `Brojačko mjesto Oznaka` |
| GIS mreža cesta (`*.gpkg`) | `LineString`/`MultiLineString` po cesti | `oznaka ceste` (npr. `DC1`) |

Brojač se identificira jednoznačno svojom šifrom; kategorija ceste (DC/AC/ŽC/LC)
deduktira se iz toga u kojem je sheetu Promet datoteke (svaki sheet pokriva
jednu kategoriju). Iz toga se gradi službena oznaka (`DC1`, `AC2`, `ŽC2042`, …)
koja se podudara s atributom `oznaka ceste` u GIS-u.

`Od`/`Do` polja u brojačkoj tablici daju opis krajeva dionice obično u obliku
druge ceste (`D207`, `Ž2258`, `A2`) ili infrastrukturne točke (`G.A.P.` =
granica administrativnog područja, naziv naselja, `čv. Lučko` itd.). Za
referentne ceste mapiramo prefiks (`D`/`A`/`Ž`/`L` → `DC`/`AC`/`ŽC`/`LC`)
kako bi se mogli prostorno locirati u GIS sloju.

---

## 2. Pretprocesiranje (skripte 01–04)

### 2.1. Učitavanje (skripta 01)

- XLS-ovi se čitaju bez headera jer prva dva retka sadrže naslov tablice. Prvi
  redak s brojem u stupcu *Brojačko mjesto Oznaka* je početak podataka.
- Svaki sheet (DC/AC/ZC/LC) ima istih 9 stupaca, osim **AC sheeta** koji ima
  8 stupaca (umjesto Početak/Kraj postoji jedan slobodni opis dionice tipa
  *„čv. Lučko – čv. Zdenčina"*); skripta to detektira po broju stupaca i
  parsira opis razdvajanjem po crti.
- Vrijednosti tipa `". . ."` (Hrvatske ceste signaliziraju "podataka nema")
  konvertiraju se u `null`.
- Rezultat je **long format** (`year × counter`) u `data/intermediate/traffic_long.csv`.

### 2.2. Prostorno spajanje brojača s mrežom (skripta 02)

Svaki brojač s GPS-om reprojecira se iz **WGS84** (EPSG:4326) u **HTRS96/TM**
(EPSG:3765) – metrički sustav GIS sloja. Algoritam:

1. Egzaktno spajanje po službenoj oznaci ceste (`DC1`, `ŽC2042`, …). Ovo daje
   najpouzdaniju identifikaciju ceste – **575 od 575** brojača s GPS-om
   uspješno se spaja po imenu.
2. Među svim segmentima te iste ceste (`MultiLineString` se eksplodira u
   pojedinačne `LineString`-ove), pronalazi se segment najbliži točki brojača.
3. Računa se **udaljenost brojač → najbliži segment**. Pouzdanost se boduje:
   - `high`  – udaljenost ≤ 30 m
   - `medium` – udaljenost ≤ 100 m
   - `low`    – udaljenost > 100 m (ali < 250 m, inače `spatial_far`)
4. Ako brojač ne pripada ni jednoj cesti po imenu (rijetko), traži se najbliži
   segment u krugu od 250 m kao fallback (`spatial_nearest`).

Rezultat je `data/intermediate/counters_matched.csv` i pomoćni
`unmatched_counters.geojson` (radi vizualne validacije).

### 2.3. Dodjela vrijednosti segmentima (skripta 03)

Algoritam je **Voronoi-jev** po linearnom mjerilu **duž svake ceste posebno**:

1. Sve segmente jedne ceste (`oznaka_ceste`) spajamo `linemerge`-om u jednu
   spojenu liniju (ako je topologija kontinuirana) ili `MultiLineString`.
2. Za svaki brojač koji pripada toj cesti izračuna se njegova *measure* (linearna
   pozicija) duž te linije pomoću `LineString.project(point)`.
3. Brojači se sortiraju po *measure*. Granice domena (segmenti pojedinog brojača)
   su sredine između susjednih *measure*-a. Krajevi ceste idu krajnjim brojačima.
4. Za svaki segment (već eksplodirani `LineString`) izračuna se *measure*
   njegovog centroida i dodjeljuje brojaču u čiju domenu pada. Confidence je
   `medium` (pouzdana cesta + pouzdana orijentacija duž nje, ali geometrija
   `Od`/`Do` nije strogo provjerena).
5. Brojači **bez GPS-a** mogu i dalje biti korisni: ako njihov `oznaka_ceste`
   postoji u mreži **i** tu cestu nitko drugi (s GPS-om) ne pokriva, vrijednost
   se dodjeljuje **cijeloj toj cesti** s confidenceom `low`. Time se ne miješa
   precizna Voronoi-jeva podjela s grubom whole-road dodjelom.

#### Edge-case obrade

- **Cesta s jednim brojačem** ⇒ cijela cesta dobiva njegove vrijednosti.
- **Cesta bez brojača** ⇒ ne pojavljuje se u izlaznom GeoJSON-u (frontend ih
  ne prikazuje).
- **Više brojača na istom segmentu** (rijetko zbog različitih smjerova
  kretanja) ⇒ Voronoi dodjeljuje segmentu jednog *vlasnika*, što izbjegava
  duplikate; ako su oba brojača na istoj točki, prednost ima onaj s
  manjom udaljenošću od mreže.

### 2.4. Manual overrides

Za ručnu intervenciju postoji `data/manual_overrides.csv`:

```csv
counter_id,year,seg_ids,note
1101,2024,123;124;125,Ručno definirana dionica
```

- `counter_id` – šifra brojača
- `year` – godina (radi traceability-ja)
- `seg_ids` – `;` razdvojen popis `seg_id` segmenata iz `network_segments.parquet`
  koje treba pripisati tom brojaču
- `note` – slobodan tekst

Override-i prepisuju automatske dodjele i njihova pouzdanost se postavlja
u `high`. Datoteka je inicijalno prazna (samo predložak).

> **Workflow za ručnu validaciju:** otvori `reports/quality_report.html` i
> `data/intermediate/unmatched_counters.geojson`, identificiraj pogrešne
> dodjele, dohvati `seg_id` iz `data/sections.geojson` (klikom na dionicu u
> aplikaciji) i upiši ih u `manual_overrides.csv`, zatim ponovno pokreni
> pipeline.

### 2.5. Izvoz za web (skripta 04)

- Geometrije se pojednostavljuju Douglas-Peuckerom (8 m tolerancija) zbog
  smanjenja veličine GeoJSON-a, uz `preserve_topology=True`.
- Reprojektiraju se u **WGS84** zbog Leafleta.
- Dionice se izvoze u **wide formatu** (`pgdp_2021`, `pgdp_2022`, …,
  `conf_2024`) – frontend filtrira po izabranoj godini bez ponovnog učitavanja.

---

## 3. Razina pouzdanosti

| Vrijednost | Značenje |
| --- | --- |
| `high`   | Ručni override; ili (u budućnosti) eksplicitna geo-validacija `Od`/`Do` granica |
| `medium` | Brojač s GPS-om, dodjela Voronoi-jevim postupkom unutar njegove ceste |
| `low`    | Brojač bez GPS-a, dodjela cijeloj cesti |
| `none`   | Dodjela nije moguća |

Aktualna distribucija (cijeli skup, prosjek po godinama):

| Pouzdanost | Otprilike % segmenata |
| --- | --- |
| medium | ~ 87 % |
| low    | ~ 13 % |
| high   | 0 % (samo override-i, ako postoje) |

---

## 4. Tretiranje nedostajućih i nelogičnih podataka

- **Nedostaju PGDP/PLDP** za neku godinu ⇒ segment za tu godinu nema vrijednost
  (frontend prikazuje `–` u tablici); za druge godine prikaz radi normalno.
- **Negativne vrijednosti** ⇒ izdvojene u `reports/issues_value_anomalies.csv`.
- **PLDP/PGDP > 3** (vrlo neuobičajen sezonski faktor) ⇒ izdvojeno isto.
- **YoY skok > ±50 %** ⇒ izdvojeno u `reports/issues_yoy_changes.csv` (može
  ukazivati na tipfeler ili promjenu lokacije brojača).
- **Brojač > 100 m od najbliže ceste** ⇒ izdvojeno u
  `reports/issues_far_from_road.csv`.

---

## 5. Ograničenja metode

1. Prag `MAX_NEAREST_M = 250 m` može biti prerestriktivan na vrlo razgranatim
   čvorovima; ako je potrebno, povećajte u skripti 02.
2. Voronoi po linearnom mjerilu pretpostavlja **kontinuiran ravan tijek
   ceste**; kod cesta koje su u GIS-u predstavljene kao više nepovezanih
   `LineString`-ova (npr. zbog rampi i obilaznica) `linemerge` može vratiti
   `MultiLineString` i mjerilo nije globalno definirano. Algoritam u tom
   slučaju koristi *measure* po pojedinoj komponenti, što je dobra
   aproksimacija ako brojači leže blizu glavnog tijeka.
3. Upotreba `Od`/`Do` referenci je trenutno informativna (prikaz u popupu),
   ali ne **strogo** rezuje dionice geometrijski – za one slučajeve gdje je
   to važno, koristite manual overrides.
4. **Brzine i struktura prometa** trenutno nisu uključene; izvor je
   nepretraživi PDF.

---

## 6. Reproducibilnost

```bash
python scripts/run_pipeline.py
```

Pipeline je deterministički — isti ulazi → isti izlazi.

Verzioniranje GIS sloja: trenutni snimak je `20250625_091453_cesta.gpkg`. Ako
Hrvatske ceste ažuriraju mrežu (nova autocesta, prerazredba), zamijenite GPKG
i ponovno pokrenite pipeline.
