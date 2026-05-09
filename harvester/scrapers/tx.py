"""TX Transportation Code scraper. STUB — implement real scraping.

Source: https://statutes.capitol.texas.gov/Docs/TN/htm/TN.{...}.htm or LII.
"""
from harvester.schema import StatuteRecord
from harvester.scrapers._base import write_records


def scrape() -> list[StatuteRecord]:
    return []


if __name__ == "__main__":
    write_records("TX", scrape())
