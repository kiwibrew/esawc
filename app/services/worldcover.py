import logging
import math
import os
import httpx
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.transform import from_bounds as transform_from_bounds
from rasterio.features import geometry_mask
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import CachedTile
from app.config import settings
from shapely.geometry import Point, mapping
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

        logging.info("Downloading tile %s from %s", tile_id, url)
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                with open(file_path, "wb") as f:
                    f.write(response.content)
                logging.info("Completed download of tile %s to %s", tile_id, file_path)
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
        logging.info(
            "get_land_cover_type: lat=%s lon=%s requires tile: %s",
            lat, lon, get_worldcover_tile_id(lat, lon)
        )
        file_path = await self.get_tile_path(lat, lon)
        with rasterio.open(file_path) as src:
            # Sample point
            vals = list(src.sample([(lon, lat)]))
            return int(vals[0][0])

    async def get_land_cover_fractions(self, lat: float, lon: float, radius_meters: float) -> dict:
        """
        Returns the fractional land cover composition within a circular area.

        How it works:
        1.  A geodesic circle is constructed by projecting to an Azimuthal Equidistant
            (AEQD) coordinate system centred on the query point, buffering by the
            requested radius in metres, then reprojecting the resulting polygon back to
            WGS84 geographic coordinates.  AEQD preserves distances from the centre
            point, so the buffer is a true geodesic circle regardless of latitude.

        2.  The WGS84 bounding box of that circle is used to identify every ESA
            WorldCover 3×3-degree tile that the circle intersects.  Each required tile
            is downloaded and cached on first use (see get_tile_path).

        3.  For each tile a *windowed read* is performed: only the small rectangular
            pixel window that overlaps the bounding box of the circle is read from
            disk.  This avoids loading the full ~2 GB tile into memory and keeps
            memory usage proportional to the query area rather than the tile size.

        4.  The windowed pixel arrays from all tiles are assembled into a single
            in-memory mosaic covering the bounding box.  Because every tile shares the
            same 10 m pixel resolution and CRS (WGS84), the arrays can be placed into
            the mosaic using simple pixel-offset arithmetic derived from each tile's
            affine transform.

        5.  A rasterio geometry mask is applied to the mosaic so that only pixels
            whose centres fall inside the WGS84 circle polygon are counted.

        6.  The surviving pixel values are tallied by ESA WorldCover class number and
            converted to fractions of the total valid pixel count.  The fractions are
            guaranteed to sum to exactly 1.0 because they are derived from integer
            counts of the same population.
        """
        # --- 1. Build geodesic buffer in WGS84 ---
        aeqd_proj = pyproj.Proj(proj='aeqd', ellps='WGS84', datum='WGS84', lat_0=lat, lon_0=lon)
        wgs84_proj = pyproj.Proj(proj='latlong', datum='WGS84')
        project_to_wgs84 = pyproj.Transformer.from_proj(aeqd_proj, wgs84_proj, always_xy=True).transform
        buffer_wgs84 = transform(project_to_wgs84, Point(0, 0).buffer(radius_meters))
        minx, miny, maxx, maxy = buffer_wgs84.bounds

        # --- 2. Identify intersecting tiles ---
        seen_tile_ids: set[str] = set()
        lon_step = math.floor(minx / 3) * 3
        while lon_step <= maxx:
            lat_step = math.floor(miny / 3) * 3
            while lat_step <= maxy:
                seen_tile_ids.add(get_worldcover_tile_id(lat_step + 1.5, lon_step + 1.5))
                lat_step += 3
            lon_step += 3

        if len(seen_tile_ids) > 1:
            logging.info(
                "get_land_cover_fractions: lat=%s lon=%s radius=%s crosses tile boundaries. Tiles required: %s",
                lat, lon, radius_meters, sorted(seen_tile_ids)
            )
        else:
            logging.info(
                "get_land_cover_fractions: lat=%s lon=%s radius=%s requires tile: %s",
                lat, lon, radius_meters, sorted(seen_tile_ids)
            )

        # Download / retrieve cached tiles
        tile_paths: list[str] = []
        for tid in sorted(seen_tile_ids):
            ns = 1 if tid[0] == "N" else -1
            ew = 1 if tid[3] == "E" else -1
            tile_lat = ns * int(tid[1:3]) + 1.5
            tile_lon = ew * int(tid[4:7]) + 1.5
            tile_paths.append(await self.get_tile_path(tile_lat, tile_lon))

        # --- 3 & 4. Windowed read and mosaic assembly ---
        # Open the first tile to get pixel resolution and CRS
        with rasterio.open(tile_paths[0]) as ref:
            res_x = ref.transform.a   # pixel width in degrees
            res_y = ref.transform.e   # pixel height (negative)

        # Compute mosaic dimensions from the buffer bounding box
        mosaic_width = max(1, math.ceil((maxx - minx) / res_x))
        mosaic_height = max(1, math.ceil((miny - maxy) / res_y))  # res_y is negative
        mosaic_transform = transform_from_bounds(minx, miny, maxx, maxy, mosaic_width, mosaic_height)
        mosaic = np.zeros((mosaic_height, mosaic_width), dtype=np.uint8)

        for path in tile_paths:
            with rasterio.open(path) as src:
                # Compute the window within this tile that overlaps the buffer bbox
                win = from_bounds(minx, miny, maxx, maxy, src.transform)
                win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
                if win.width <= 0 or win.height <= 0:
                    continue

                tile_data = src.read(1, window=win)
                tile_win_transform = src.window_transform(win)

                # Compute where this window lands in the mosaic (pixel offsets)
                col_off = round((tile_win_transform.c - minx) / res_x)
                row_off = round((tile_win_transform.f - maxy) / res_y)

                # Clip to mosaic bounds
                src_row_start = max(0, -row_off)
                src_col_start = max(0, -col_off)
                dst_row_start = max(0, row_off)
                dst_col_start = max(0, col_off)
                rows = min(tile_data.shape[0] - src_row_start, mosaic_height - dst_row_start)
                cols = min(tile_data.shape[1] - src_col_start, mosaic_width - dst_col_start)
                if rows <= 0 or cols <= 0:
                    continue

                mosaic[
                    dst_row_start:dst_row_start + rows,
                    dst_col_start:dst_col_start + cols,
                ] = tile_data[src_row_start:src_row_start + rows, src_col_start:src_col_start + cols]

        # --- 5. Apply geometry mask ---
        geom_mask = geometry_mask(
            [mapping(buffer_wgs84)],
            transform=mosaic_transform,
            invert=True,
            out_shape=(mosaic_height, mosaic_width),
        )
        valid_data = mosaic[geom_mask & (mosaic != 0)]

        # --- 6. Count pixels and return fractions ---
        if len(valid_data) == 0:
            return {}

        unique, counts = np.unique(valid_data, return_counts=True)
        total = counts.sum()
        fractions = {str(int(u)): float(c / total) for u, c in zip(unique, counts)}
        return fractions
