"""NY Vehicle and Traffic Law scraper. STUB — implement real scraping.

Source: https://www.nysenate.gov/legislation/laws/VAT or LII.
"""
from harvester.schema import StatuteRecord
from harvester.scrapers._base import write_records


def scrape() -> list[StatuteRecord]:
    return []


if __name__ == "__main__":
    write_records("NY", scrape())
