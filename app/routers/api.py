import json

from fastapi import APIRouter, Depends, File, HTTPException, Security, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.worldcover import GeoJSONNoTileCoverageError, WorldCoverService
from app.dependencies import get_current_active_user
from app.models.models import User

bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api", tags=["API"])

@router.get("/land-cover")
async def get_land_cover(
    lat: float,
    lon: float,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    _credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
):
    service = WorldCoverService(db)
    try:
        lc_class = await service.get_land_cover_type(lat, lon)
        return {"class": lc_class}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/land-cover-fractions")
async def get_land_cover_fractions(
    lat: float,
    lon: float,
    radius: float,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    _credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
):
    """
    Returns fractional land cover composition within a circular area.

    **radius** must be between 1 and 100,000 metres (100 km). Requests exceeding
    this limit are rejected with HTTP 422.
    """
    if radius <= 0 or radius > 100_000:
        raise HTTPException(status_code=422, detail="radius must be between 1 and 100000 metres (100 km).")
    service = WorldCoverService(db)
    try:
        fractions = await service.get_land_cover_fractions(lat, lon, radius)
        return fractions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/land-cover-geojson")
async def post_land_cover_geojson(
    geojson_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    _credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
):
    service = WorldCoverService(db)
    try:
        geojson = json.loads(await geojson_file.read())
        if not isinstance(geojson, dict):
            raise HTTPException(status_code=422, detail="geojson file must contain a JSON object")
        return await service.get_land_cover_for_geojson(geojson)
    except GeoJSONNoTileCoverageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="geojson file is not valid JSON")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
