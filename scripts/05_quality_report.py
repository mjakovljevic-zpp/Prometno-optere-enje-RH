"""05 - Validacija i izvjestaj o kvaliteti.

Generira:
  reports/quality_report.html
  reports/issues_counters_no_gps.csv
  reports/issues_far_from_road.csv
  reports/issues_value_anomalies.csv
  reports/issues_yoy_changes.csv
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
DATA_DIR = PROJECT_ROOT / "data"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

YOY_CHANGE_THRESHOLD = 0.50   # vise od +/-50 % izmedju dvije godine je sumnjivo
PLDP_OVER_PGDP_RATIO = 3.0    # PLDP/PGDP > 3 je vrlo neuobicajeno


def main():
    print("[05] Validacija", flush=True)
    matched = pd.read_csv(INTERMEDIATE_DIR / "counters_matched.csv", dtype={"counter_id": str})
    traffic = pd.read_csv(INTERMEDIATE_DIR / "traffic_long.csv", dtype={"counter_id": str})

    # 1) Brojaci bez GPS-a
    no_gps = traffic[traffic["lat"].isna() | traffic["lon"].isna()][
        ["counter_id", "year", "category", "oznaka_ceste", "naziv", "od", "do", "pgdp", "pldp"]
    ].drop_duplicates(subset=["counter_id"])
    no_gps.to_csv(REPORTS_DIR / "issues_counters_no_gps.csv", index=False)
    print(f"     {len(no_gps)} brojaca bez GPS-a", flush=True)

    # 2) Daleko od mreze
    far = matched[matched["dist_m"].fillna(0) > 100].sort_values("dist_m", ascending=False)
    far.to_csv(REPORTS_DIR / "issues_far_from_road.csv", index=False)
    print(f"     {len(far)} brojaca > 100 m od najblize ceste", flush=True)

    # 3) Vrijednosne anomalije
    anomalies = traffic.copy()
    anomalies["pldp_over_pgdp"] = anomalies["pldp"] / anomalies["pgdp"].replace(0, np.nan)
    bad = anomalies[
        (anomalies["pgdp"].fillna(0) < 0)
        | (anomalies["pldp"].fillna(0) < 0)
        | (anomalies["pldp_over_pgdp"].fillna(0) > PLDP_OVER_PGDP_RATIO)
    ]
    bad.to_csv(REPORTS_DIR / "issues_value_anomalies.csv", index=False)
    print(f"     {len(bad)} redaka s neobicnim vrijednostima", flush=True)

    # 4) Year-over-year skok
    yoy_rows = []
    for cid, g in traffic.sort_values("year").groupby("counter_id"):
        prev = None
        for _, r in g.iterrows():
            cur = r["pgdp"]
            if prev is not None and cur is not None and prev > 0:
                ch = (cur - prev) / prev
                if abs(ch) > YOY_CHANGE_THRESHOLD:
                    yoy_rows.append({
                        "counter_id": cid, "naziv": r["naziv"], "oznaka_ceste": r["oznaka_ceste"],
                        "year": int(r["year"]), "pgdp": cur, "pgdp_prev": prev, "change_pct": ch * 100,
                    })
            prev = cur if pd.notna(cur) else prev
    yoy = pd.DataFrame(yoy_rows)
    yoy.to_csv(REPORTS_DIR / "issues_yoy_changes.csv", index=False)
    print(f"     {len(yoy)} velikih medugodisnjih skokova", flush=True)

    # HTML izvjestaj
    html_path = REPORTS_DIR / "quality_report.html"
    if html_path.exists():
        try:
            html_path.unlink()
        except Exception:
            pass

    def _table_html(df, max_rows=50):
        if len(df) == 0:
            return "<p><em>Nema zapisa.</em></p>"
        return df.head(max_rows).to_html(index=False, classes="data", border=0, na_rep="–")

    summary_path = DATA_DIR / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

    style = (
        "body{font-family:'Inter',sans-serif;color:#1f2937;max-width:1100px;margin:24px auto;"
        "padding:0 24px;}"
        "h1{font-weight:600;}h2{border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin-top:32px;}"
        "table.data{border-collapse:collapse;width:100%;font-size:14px;}"
        "table.data th{background:#f3f4f6;text-align:left;padding:6px 8px;}"
        "table.data td{padding:6px 8px;border-top:1px solid #e5e7eb;}"
        ".pill{display:inline-block;padding:2px 8px;border-radius:12px;font-size:12px;"
        "background:#eef2ff;color:#3730a3;margin-right:6px;}"
    )

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>Validacija - Karta prometnog opterecenja</title>",
        f"<style>{style}</style></head><body>",
        "<h1>Validacija podataka prometnog opterecenja</h1>",
        f"<p>Godine: {', '.join(map(str, summary.get('years', [])))}.</p>",
    ]
    if summary.get("by_year"):
        parts.append("<h2>Sazetak po godini</h2><table class='data'><tr><th>Godina</th><th>Dionica</th>"
                     "<th>Duljina (km)</th><th>Avg PGDP</th><th>Max PGDP</th><th>Avg PLDP</th></tr>")
        for yr, s in sorted(summary["by_year"].items()):
            parts.append(
                f"<tr><td>{yr}</td><td>{s.get('n_sections')}</td>"
                f"<td>{s.get('total_length_km'):.1f}</td>"
                f"<td>{s.get('avg_pgdp'):.0f}</td>"
                f"<td>{s.get('max_pgdp'):.0f}</td>"
                f"<td>{s.get('avg_pldp'):.0f}</td></tr>"
            )
        parts.append("</table>")

    parts.append(f"<h2>Brojaci bez GPS-a ({len(no_gps)})</h2>")
    parts.append(_table_html(no_gps))
    parts.append(f"<h2>Brojaci dalje od 100 m od mreze ({len(far)})</h2>")
    parts.append(_table_html(far[["counter_id", "naziv", "oznaka_ceste", "dist_m", "match_method", "confidence"]]))
    parts.append(f"<h2>Vrijednosne anomalije ({len(bad)})</h2>")
    parts.append(_table_html(bad[["counter_id", "year", "oznaka_ceste", "pgdp", "pldp", "pldp_over_pgdp"]]))
    parts.append(f"<h2>Veliki skokovi izmedju godina ({len(yoy)})</h2>")
    parts.append(_table_html(yoy))
    parts.append("</body></html>")

    html_path.write_text("\n".join(parts), encoding="utf-8")
    print(f"[05] reports/quality_report.html ({html_path.stat().st_size//1024} kB)", flush=True)
    print("[05] OK", flush=True)


if __name__ == "__main__":
    main()
