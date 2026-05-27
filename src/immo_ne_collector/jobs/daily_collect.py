import asyncio

from immo_ne_collector.scrapers.example_static import ExampleStaticScraper


async def run_daily_collection() -> int:
    scrapers = [ExampleStaticScraper()]
    total = 0
    for scraper in scrapers:
        listings = await scraper.collect()
        # TODO: normaliser, upsert source_listings, dedupliquer, mettre a jour properties.
        total += len(listings)
    print(f"Collected {total} listings")
    return total


def main() -> None:
    asyncio.run(run_daily_collection())


if __name__ == "__main__":
    main()
