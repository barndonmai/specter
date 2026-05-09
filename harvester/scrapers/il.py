"""IL Vehicle Code (625 ILCS 5) scraper. STUB — implement real scraping.

Source: https://www.ilga.gov/legislation/ilcs/ilcs5.asp?ActID=1815 or LII.
"""
from harvester.schema import StatuteRecord
from harvester.scrapers._base import write_records


def scrape() -> list[StatuteRecord]:
    return []


if __name__ == "__main__":
    write_records("IL", scrape())
