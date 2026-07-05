from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.services.worldcover import WorldCoverService
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
    service = WorldCoverService(db)
    try:
        fractions = await service.get_land_cover_fractions(lat, lon, radius)
        return fractions
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
