"""FL Statutes Ch. 316 scraper. STUB — implement real scraping.

Source: https://www.flsenate.gov/Laws/Statutes/2024/Chapter316/All or LII.
"""
from harvester.schema import StatuteRecord
from harvester.scrapers._base import write_records


def scrape() -> list[StatuteRecord]:
    return []


if __name__ == "__main__":
    write_records("FL", scrape())
