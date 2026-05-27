from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.get("/properties")
async def list_properties() -> dict[str, list]:
    # TODO: brancher la DB et les filtres.
    return {"items": []}


@router.get("/properties/new")
async def list_new_properties() -> dict[str, list]:
    return {"items": []}


@router.get("/properties/updated")
async def list_updated_properties() -> dict[str, list]:
    return {"items": []}


@router.get("/properties/inactive")
async def list_inactive_properties() -> dict[str, list]:
    return {"items": []}
