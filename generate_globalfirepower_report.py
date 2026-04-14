#!/usr/bin/env python3
"""
Generate a PDF report from Global Firepower 2026 data.

Output:
  - /workspace/globalfirepower_military_report_2026.pdf
"""

from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import requests
from fpdf import FPDF


BASE_SITE = "http://www.globalfirepower.com"
MIRROR_PREFIX = "https://r.jina.ai/"
OUTPUT_PDF = Path("/workspace/globalfirepower_military_report_2026.pdf")


@dataclass
class RankedCountry:
    rank: int
    name: str
    pwr_indx: str
    detail_url: str


def mirror_url(source_url: str) -> str:
    return f"{MIRROR_PREFIX}{source_url}"


def fetch_text(source_url: str, retries: int = 4) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(
                mirror_url(source_url), headers=headers, timeout=120
            )
            response.raise_for_status()
            text = response.text
            if "Markdown Content:" not in text:
                raise RuntimeError("Unexpected mirror response format")
            return text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed to fetch {source_url}: {last_error}") from last_error


def parse_rankings(ranking_text: str) -> List[RankedCountry]:
    ranking_pattern = re.compile(
        r"\[(\d{1,3})\s+([A-Za-z][A-Za-z .&'\-()]+?)\s+[A-Z]{2,4}\s+"
        r"!\[Image\s+\d+:[^\]]*\]"
        r"\(http://www\.globalfirepower\.com/imgs/misc/arrow-[^)]+\)\s*"
        r"PwrIndx:\s*([0-9.]+)\]\("
        r"(http://www\.globalfirepower\.com/country-military-strength-detail\.php\?country_id=[^) \n]+)",
        re.S,
    )

    rows: List[RankedCountry] = []
    for match in ranking_pattern.finditer(ranking_text):
        rank = int(match.group(1))
        name = " ".join(match.group(2).split())
        pwr_indx = match.group(3)
        detail_url = match.group(4)
        rows.append(RankedCountry(rank, name, pwr_indx, detail_url))

    rows.sort(key=lambda row: row.rank)
    if len(rows) != 145 or rows[0].rank != 1 or rows[-1].rank != 145:
        raise RuntimeError(
            f"Unexpected ranking parse result: count={len(rows)}, "
            f"first={rows[0].rank if rows else 'n/a'}, "
            f"last={rows[-1].rank if rows else 'n/a'}"
        )
    return rows


def extract_tot_personnel(country_text: str) -> str:
    match = re.search(
        r"Tot Mil\. Personnel \(est\.\)\s*\n+\s*([0-9,]+)", country_text, re.I
    )
    return match.group(1) if match else "N/A"


def extract_metric(country_text: str, label: str) -> str:
    escaped = re.escape(label)
    patterns = [
        rf"\d+/\d+\s+{escaped}:\s*Stock:\s*([0-9,]+)",
        rf"\d+/\d+\s+{escaped}:\s*([0-9,]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, country_text, re.I)
        if match:
            return match.group(1)
    return "N/A"


def extract_drones(country_text: str) -> str:
    patterns = [
        r"\d+/\d+\s+Drones:\s*(?:Stock:\s*)?([0-9,]+)",
        r"\d+/\d+\s+UAVs?:\s*(?:Stock:\s*)?([0-9,]+)",
        r"\d+/\d+\s+Unmanned Aerial Vehicles:\s*(?:Stock:\s*)?([0-9,]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, country_text, re.I)
        if match:
            return match.group(1)
    return "Not listed on GFP country page"


def fetch_top25_details(top_25: List[RankedCountry]) -> Dict[int, Dict[str, str]]:
    details: Dict[int, Dict[str, str]] = {}
    metric_map = {
        "Total Military Personnel (est.)": ("tot_personnel", None),
        "Aircraft Total": ("metric", "Aircraft Total"),
        "Fighter Jets": ("metric", "Fighters"),
        "Attack Aircraft": ("metric", "Attack Types"),
        "Transport Aircraft": ("metric", "Transports (Fixed-Wing)"),
        "Helicopters": ("metric", "Helicopters"),
        "Attack Helicopters": ("metric", "Attack Helicopters"),
        "Tanks": ("metric", "Tanks"),
        "Self-Propelled Artillery": ("metric", "Self-Propelled Artillery"),
        "Rocket Artillery (MLRS)": ("metric", "MLRS (Rocket Artillery)"),
        "Fleet Total (Warships)": ("metric", "Fleet Total"),
        "Submarines": ("metric", "Submarines"),
        "Destroyers": ("metric", "Destroyers"),
        "Frigates": ("metric", "Frigates"),
        "Corvettes": ("metric", "Corvettes"),
        "Patrol Vessels": ("metric", "Patrol Vessels"),
        "Drones / UAVs": ("drones", None),
    }

    for country in top_25:
        text = fetch_text(country.detail_url)
        parsed: Dict[str, str] = {}
        for display_name, (mode, raw_label) in metric_map.items():
            if mode == "tot_personnel":
                parsed[display_name] = extract_tot_personnel(text)
            elif mode == "drones":
                parsed[display_name] = extract_drones(text)
            else:
                parsed[display_name] = extract_metric(text, raw_label or "")
        details[country.rank] = parsed
    return details


class ReportPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 10)
        self.cell(
            0,
            7,
            "Global Firepower 2026 Military Report",
            align="R",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.ln(1)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")


def add_rank_list_section(pdf: ReportPDF, title: str, countries: List[RankedCountry]) -> None:
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 10)
    for c in countries:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(
            0,
            6,
            f"{c.rank:>3}. {c.name} (PwrIndx: {c.pwr_indx})",
            new_x="LMARGIN",
            new_y="NEXT",
        )


def add_top25_details_section(
    pdf: ReportPDF,
    top_25: List[RankedCountry],
    details: Dict[int, Dict[str, str]],
) -> None:
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        0,
        8,
        "Top 25 Countries - Basic Military Information",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(1)

    for country in top_25:
        values = details[country.rank]
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(
            0,
            7,
            f"#{country.rank} {country.name} (PwrIndx: {country.pwr_indx})",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("Helvetica", "", 10)
        for key, value in values.items():
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(
                0,
                5,
                f"- {key}: {value}",
                new_x="LMARGIN",
                new_y="NEXT",
            )
        pdf.ln(2)


def build_pdf_report(
    rankings: List[RankedCountry],
    details: Dict[int, Dict[str, str]],
    output_path: Path,
) -> None:
    top_50 = rankings[:50]
    bottom_50 = rankings[-50:]
    top_25 = rankings[:25]

    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        0,
        10,
        "Global Firepower 2026 Military Power Report",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 11)
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, 7, f"Generated: {generated}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        0,
        7,
        "Source: https://www.globalfirepower.com/countries-listing.php",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        0,
        7,
        "Coverage: Top 50, Bottom 50, and Top 25 detail snapshot",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    add_rank_list_section(pdf, "Top 50 Military Powers (2026 GFP)", top_50)
    add_rank_list_section(pdf, "Bottom 50 Military Powers (2026 GFP)", bottom_50)
    add_top25_details_section(pdf, top_25, details)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def main() -> None:
    ranking_text = fetch_text(f"{BASE_SITE}/countries-listing.php")
    rankings = parse_rankings(ranking_text)
    top_25_details = fetch_top25_details(rankings[:25])
    build_pdf_report(rankings, top_25_details, OUTPUT_PDF)
    print(f"Created PDF report: {OUTPUT_PDF}")


if __name__ == "__main__":
    main()
