from immo_ne_collector.scrapers.base import BaseScraper, RawListing


class ExampleStaticScraper(BaseScraper):
    source = "example"

    async def collect(self) -> list[RawListing]:
        # Exemple volontairement statique pour tester le pipeline sans scraper reel.
        return [
            RawListing(
                source=self.source,
                source_listing_id="ex-1",
                url="https://example.test/annonce/1",
                title="Appartement 4.5 pieces a Neuchatel",
                property_type="appartement",
                city_raw="Neuchatel",
                price_raw="CHF 850'000",
                living_area_raw="110 m2",
                rooms_raw="4.5",
                raw_data={"demo": True},
            )
        ]
