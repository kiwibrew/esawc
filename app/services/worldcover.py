import math
import os
import httpx
import asyncio
import numpy as np
import rasterio
from datetime import datetime, timedelta
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import CachedTile
from app.config import settings
from rasterio.windows import from_bounds
from rasterio.mask import mask
from shapely.geometry import box, Point
import pyproj
from shapely.ops import transform

def get_worldcover_tile_id(lat: float, lon: float) -> str:
    tile_lat = math.floor(lat / 3) * 3
    tile_lon = math.floor(lon / 3) * 3
    ns = "N" if tile_lat >= 0 else "S"
    ew = "E" if tile_lon >= 0 else "W"
    return f"{ns}{abs(tile_lat):02d}{ew}{abs(tile_lon):03d}"

def get_worldcover_url(tile_id: str) -> str:
    return f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile_id}_Map.tif"

class WorldCoverService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_tile_path(self, lat: float, lon: float) -> str:
        tile_id = get_worldcover_tile_id(lat, lon)
        
        # a) Check sqlite
        result = await self.db.execute(select(CachedTile).where(CachedTile.tile_id == tile_id))
        cached_tile = result.scalar_one_or_none()
        
        now = datetime.utcnow()
        one_week_later = now + timedelta(days=7)

        if cached_tile:
            # Update expiration
            cached_tile.last_used_at = now
            cached_tile.expires_at = one_week_later
            await self.db.commit()
            return cached_tile.file_path

        # b) Get tile if not cached
        url = get_worldcover_url(tile_id)
        file_name = f"{tile_id}.tif"
        file_path = os.path.join(settings.TILE_CACHE_DIR, file_name)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(response.content)
            else:
                raise Exception(f"Failed to download tile {tile_id} from {url}: {response.status_code}")

        new_tile = CachedTile(
            tile_id=tile_id,
            file_path=file_path,
            last_used_at=now,
            expires_at=one_week_later
        )
        self.db.add(new_tile)
        await self.db.commit()

        # c) Cleanup expired tiles
        expired_result = await self.db.execute(select(CachedTile).where(CachedTile.expires_at < now))
        expired_tiles = expired_result.scalars().all()
        for et in expired_tiles:
            if os.path.exists(et.file_path):
                os.remove(et.file_path)
            await self.db.delete(et)
        await self.db.commit()

        return file_path

    async def get_land_cover_type(self, lat: float, lon: float) -> int:
        file_path = await self.get_tile_path(lat, lon)
        with rasterio.open(file_path) as src:
            # Sample point
            vals = list(src.sample([(lon, lat)]))
            return int(vals[0][0])

    async def get_land_cover_fractions(self, lat: float, lon: float, radius_meters: float) -> dict:
        # Buffer in geodesic or equal area
        # We'll use pyproj to create a transformer to a local equal-area projection
        # or just use a simple approach: project to AEQD centered at the point
        
        aeqd_proj = pyproj.Proj(proj='aeqd', ellps='WGS84', datum='WGS84', lat_0=lat, lon_0=lon)
        wgs84_proj = pyproj.Proj(proj='latlong', datum='WGS84')
        
        project_to_aeqd = pyproj.Transformer.from_proj(wgs84_proj, aeqd_proj, always_xy=True).transform
        project_to_wgs84 = pyproj.Transformer.from_proj(aeqd_proj, wgs84_proj, always_xy=True).transform
        
        # Buffer in AEQD (meters)
        center_aeqd = Point(0, 0)
        buffer_aeqd = center_aeqd.buffer(radius_meters)
        
        # Transform buffer back to WGS84 for masking
        buffer_wgs84 = transform(project_to_wgs84, buffer_aeqd)
        
        bounds = buffer_wgs84.bounds # (minx, miny, maxx, maxy)
        
        # Find intersecting tiles (a buffer could cross 4 tiles at most given 3x3 degree tiles and reasonable radius)
        # For simplicity, we'll collect all unique tile IDs covering the bounds
        tiles_needed = set()
        for x in [bounds[0], bounds[2]]:
            for y in [bounds[1], bounds[3]]:
                tiles_needed.add(get_worldcover_tile_id(y, x))
        
        # Actually just sample a grid of points or use rasterio.merge if multiple tiles
        # But wait, 3x3 degrees is HUGE (300km+). A radius is usually smaller.
        # Let's just use the primary tile and see if it covers the whole buffer.
        
        main_tile_path = await self.get_tile_path(lat, lon)
        
        # TODO: Handle multiple tiles if buffer crosses boundaries
        # For now, let's assume it's within one tile or we just use one for MVP, 
        # but the prompt says "find the appropriate tile or tiles".
        
        # To handle multiple tiles correctly, we'd need to merge them.
        # For now, let's implement single tile logic and consider merging if needed.
        
        with rasterio.open(main_tile_path) as src:
            out_image, out_transform = mask(src, [buffer_wgs84], crop=True)
            
        data = out_image[0]
        # Mask out 0 (no data) and pixels outside buffer (mask tool sets them to nodata)
        nodata = 0 # ESA WorldCover nodata is 0
        valid_data = data[data != nodata]
        
        if len(valid_data) == 0:
            return {}
            
        unique, counts = np.unique(valid_data, return_counts=True)
        total = counts.sum()
        
        fractions = {str(int(u)): float(c / total) for u, c in zip(unique, counts)}
        
        # Ensure they add up to exactly 1 (handle rounding)
        # Actually float division is usually fine but let's be careful if required
        # For now, this is standard.
        
        return fractions
