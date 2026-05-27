from dataclasses import dataclass

from immo_ne_collector.scrapers.base import BaseScraper, RawListing


@dataclass(frozen=True)
class MockListingSeed:
    source_listing_id: str
    url: str
    title: str | None = None
    property_type: str | None = None
    price_raw: str | None = None
    rooms_raw: str | None = None
    living_area_raw: str | None = None
    address_raw: str | None = None
    city_raw: str | None = None
    postal_code_raw: str | None = None
    description_raw: str | None = None


class CatalogMockScraper(BaseScraper):
    source = "mock_catalog"

    def __init__(self, *, source: str, seeds: list[MockListingSeed]) -> None:
        self.source = source
        self._seeds = seeds
        super().__init__()

    async def collect(self) -> list[RawListing]:
        return [
            RawListing(
                source=self.source,
                source_listing_id=seed.source_listing_id,
                url=seed.url,
                title=seed.title,
                property_type=seed.property_type,
                price_raw=seed.price_raw,
                rooms_raw=seed.rooms_raw,
                living_area_raw=seed.living_area_raw,
                address_raw=seed.address_raw,
                city_raw=seed.city_raw,
                postal_code_raw=seed.postal_code_raw,
                description_raw=seed.description_raw,
                raw_data={"mock_multi_source": True, "source": self.source},
            )
            for seed in self._seeds
        ]


def build_demo_multisource_scrapers() -> list[CatalogMockScraper]:
    return [
        CatalogMockScraper(
            source="mock_homegate",
            seeds=[
                MockListingSeed(
                    source_listing_id="hg-1",
                    url="https://mock.homegate.local/hg-1",
                    title="Appartement 4.5 pieces a Neuchatel",
                    property_type="appartement",
                    price_raw="CHF 850'000",
                    rooms_raw="4.5",
                    living_area_raw="110 m2",
                    address_raw="Rue du Seyon 12",
                    city_raw="Neuchatel",
                    postal_code_raw="2000",
                    description_raw="Annonce source Homegate mock.",
                )
            ],
        ),
        CatalogMockScraper(
            source="mock_immoscout",
            seeds=[
                MockListingSeed(
                    source_listing_id="is-1",
                    url="https://mock.immoscout.local/is-1",
                    title="Bel appartement 4.5 pieces Neuchatel",
                    property_type="appartement",
                    price_raw="CHF 855'000",
                    rooms_raw="4.5",
                    living_area_raw="112 m2",
                    address_raw="Rue du Seyon 12",
                    city_raw="Neuchatel",
                    postal_code_raw="2000",
                    description_raw="Annonce source ImmoScout mock.",
                ),
                MockListingSeed(
                    source_listing_id="is-2",
                    url="https://mock.immoscout.local/is-2",
                    title="Maison 6 pieces a La Chaux-de-Fonds",
                    property_type="maison",
                    price_raw="CHF 1'150'000",
                    rooms_raw="6",
                    living_area_raw="165 m2",
                    address_raw="Avenue Leopold-Robert 45",
                    city_raw="La Chaux-de-Fonds",
                    postal_code_raw="2300",
                    description_raw="Annonce differente qui doit rester separee.",
                ),
            ],
        ),
    ]
