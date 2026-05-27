from immo_ne_collector.scrapers.base import BaseScraper, RawListing


class MockScraper(BaseScraper):
    source = "mock"

    async def collect(self) -> list[RawListing]:
        return [
            RawListing(
                source=self.source,
                source_listing_id="m-1001",
                url="https://mock.local/listings/m-1001",
                title="Appartement 4.5 pieces a Neuchatel",
                property_type="appartement",
                price_raw="CHF 850'000",
                rooms_raw="4.5",
                living_area_raw="110 m2",
                address_raw="Rue du Seyon 12",
                city_raw="Neuchatel",
                postal_code_raw="2000",
                description_raw="Annonce fictive pour tests unitaires.",
                raw_data={"mock": True, "rank": 1},
            ),
            RawListing(
                source=self.source,
                source_listing_id="m-1002",
                url="https://mock.local/listings/m-1002",
                title="Maison 6 pieces a La Chaux-de-Fonds",
                property_type="maison",
                price_raw="CHF 1'150'000",
                rooms_raw="6",
                living_area_raw="165 m2",
                address_raw="Avenue Leopold-Robert 45",
                city_raw="La Chaux-de-Fonds",
                postal_code_raw="2300",
                description_raw="Deuxieme annonce fictive.",
                raw_data={"mock": True, "rank": 2},
            ),
            RawListing(
                source=self.source,
                source_listing_id="m-1003",
                url="https://mock.local/listings/m-1003",
                title="Immeuble de rendement a Boudry",
                property_type="immeuble",
                price_raw="CHF 2'300'000",
                rooms_raw=None,
                living_area_raw="450 m2",
                address_raw="Rue Louis-Favre 7",
                city_raw="Boudry",
                postal_code_raw="2017",
                description_raw="Troisieme annonce fictive.",
                raw_data={"mock": True, "rank": 3},
            ),
        ]
