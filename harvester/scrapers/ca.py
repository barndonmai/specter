"""
California Vehicle Code scraper.

⚠️ STUB — the team member on this track must implement actual scraping.

Recommended source: Cornell LII (https://www.law.cornell.edu/) or
California Legislative Info (https://leginfo.legislature.ca.gov/).

LII is usually easier to parse uniformly across states. leginfo is more
authoritative for source_url citation purposes.

Output contract: writes data/raw/ca.json — a list of StatuteRecord dicts.
"""
from __future__ import annotations
from harvester.schema import StatuteRecord, make_id
from harvester.scrapers._base import client, polite_sleep, write_records


def scrape() -> list[StatuteRecord]:
    records: list[StatuteRecord] = []

    # TODO: real scraper. For now we emit ONE smoke-test record so the
    # downstream pipeline (tag → load → serve → eval) can be exercised
    # end-to-end before the real scraper lands.
    records.append(StatuteRecord(
        id=make_id("CA", "vc", "23152(a)"),
        jurisdiction="California",
        state_code="CA",
        code="Cal. Veh. Code",
        section="23152(a)",
        citation="Cal. Veh. Code § 23152(a)",
        title="Driving under the influence of alcohol",
        text=("It is unlawful for any person who is under the influence of any "
              "alcoholic beverage to drive a vehicle."),
        hierarchy_path=["Vehicle Code", "Division 11", "Chapter 12", "Article 2"],
        source_url="https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=VEH&sectionNum=23152.",
    ))

    return records


if __name__ == "__main__":
    write_records("CA", scrape())
