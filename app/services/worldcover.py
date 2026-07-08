import logging
import math
import os
from collections.abc import Iterator
import httpx
import numpy as np
import rasterio
from rasterio.errors import WindowError
from rasterio.windows import from_bounds
from rasterio.features import geometry_mask
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import CachedTile
from app.config import settings
from shapely.geometry import GeometryCollection, Point, box, mapping, shape
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


class GeoJSONNoTileCoverageError(ValueError):
    def __init__(self):
        super().__init__("geojson does not have any coverage of any available tiles")


def _extract_geometries(geojson: dict) -> list:
    geo_type = geojson.get("type")
    if geo_type == "FeatureCollection":
        geometries = []
        for feature in geojson.get("features", []):
            if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict):
                geometries.extend(_extract_geometries(feature["geometry"]))
        return geometries

    if geo_type == "Feature":
        geometry = geojson.get("geometry")
        if not isinstance(geometry, dict):
            return []
        return _extract_geometries(geometry)

    return [shape(geojson)]


def _tile_origin_from_tile_id(tile_id: str) -> tuple[float, float]:
    lat_sign = 1 if tile_id[0] == "N" else -1
    lon_sign = 1 if tile_id[3] == "E" else -1
    return lat_sign * int(tile_id[1:3]), lon_sign * int(tile_id[4:7])


class WorldCoverService:
    WINDOW_CHUNK_SIZE = 2048

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
        return await self._get_land_cover_type_from_point(Point(lon, lat))

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

        3.  For each intersecting tile a windowed read is performed so only the pixel
            region overlapping the geometry is loaded into memory.

        4.  A rasterio geometry mask is applied tile by tile so only pixels whose
            centres fall inside the WGS84 circle polygon are counted.

        5.  The surviving pixel values are tallied by ESA WorldCover class number and
            converted to fractions of the total valid pixel count.  The fractions are
            guaranteed to sum to exactly 1.0 because they are derived from integer
            counts of the same population.
        """
        # --- 1. Build geodesic buffer in WGS84 ---
        aeqd_proj = pyproj.Proj(proj='aeqd', ellps='WGS84', datum='WGS84', lat_0=lat, lon_0=lon)
        wgs84_proj = pyproj.Proj(proj='latlong', datum='WGS84')
        project_to_wgs84 = pyproj.Transformer.from_proj(aeqd_proj, wgs84_proj, always_xy=True).transform
        buffer_wgs84 = transform(project_to_wgs84, Point(0, 0).buffer(radius_meters))

        counts = await self._get_land_cover_counts_for_geometries([buffer_wgs84], raise_on_empty=False)
        if not counts:
            return {}
        total = sum(counts.values())
        return {str(class_id): float(count / total) for class_id, count in sorted(counts.items())}

    async def get_land_cover_for_geojson(self, geojson: dict) -> dict:
        geometries = [geom for geom in _extract_geometries(geojson) if not geom.is_empty]
        if not geometries:
            raise GeoJSONNoTileCoverageError()

        if len(geometries) == 1 and geometries[0].geom_type == "Point":
            return {"class": await self._get_land_cover_type_from_point(geometries[0], raise_on_empty=True)}

        counts = await self._get_land_cover_counts_for_geometries(geometries, raise_on_empty=True)
        total = sum(counts.values())
        return {str(class_id): float(count / total) for class_id, count in sorted(counts.items())}

    async def _get_land_cover_type_from_point(self, point: Point, raise_on_empty: bool = False) -> int:
        file_path = await self.get_tile_path(point.y, point.x)
        with rasterio.open(file_path) as src:
            sample = next(src.sample([(point.x, point.y)], masked=True))
            value = sample[0]
            if np.ma.is_masked(value) or int(value) == 0:
                if raise_on_empty:
                    raise GeoJSONNoTileCoverageError()
                return 0
            return int(value)

    async def _get_land_cover_counts_for_geometries(
        self,
        geometries: list,
        *,
        raise_on_empty: bool,
    ) -> dict[int, int]:
        tile_ids = self._get_intersecting_tile_ids(geometries)
        if not tile_ids:
            if raise_on_empty:
                raise GeoJSONNoTileCoverageError()
            return {}

        counts: dict[int, int] = {}
        for tile_id in sorted(tile_ids):
            tile_lat, tile_lon = _tile_origin_from_tile_id(tile_id)
            file_path = await self.get_tile_path(tile_lat + 1.5, tile_lon + 1.5)

            with rasterio.open(file_path) as src:
                tile_bounds = box(*src.bounds)
                tile_geometries = [geom for geom in geometries if geom.intersects(tile_bounds)]
                if not tile_geometries:
                    continue

                minx, miny, maxx, maxy = GeometryCollection(tile_geometries).bounds
                if any(math.isinf(value) for value in (minx, miny, maxx, maxy)):
                    continue

                win = from_bounds(minx, miny, maxx, maxy, src.transform)
                try:
                    win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
                except WindowError:
                    continue

                if win.width <= 0 or win.height <= 0:
                    continue

                for chunk_counts in self._iter_tile_window_counts(src, win, tile_geometries):
                    for land_cover_class, count in chunk_counts.items():
                        counts[land_cover_class] = counts.get(land_cover_class, 0) + count

        if not counts and raise_on_empty:
            raise GeoJSONNoTileCoverageError()

        return counts

    def _iter_tile_window_counts(self, src, win, tile_geometries: list) -> Iterator[dict[int, int]]:
        row_start = max(0, math.floor(win.row_off))
        col_start = max(0, math.floor(win.col_off))
        row_stop = min(src.height, math.ceil(win.row_off + win.height))
        col_stop = min(src.width, math.ceil(win.col_off + win.width))

        for row_off in range(row_start, row_stop, self.WINDOW_CHUNK_SIZE):
            for col_off in range(col_start, col_stop, self.WINDOW_CHUNK_SIZE):
                chunk_win = rasterio.windows.Window(
                    col_off=col_off,
                    row_off=row_off,
                    width=min(self.WINDOW_CHUNK_SIZE, col_stop - col_off),
                    height=min(self.WINDOW_CHUNK_SIZE, row_stop - row_off),
                )
                tile_data = src.read(1, window=chunk_win, masked=True)
                if tile_data.size == 0:
                    continue

                geom_mask = geometry_mask(
                    [mapping(geom) for geom in tile_geometries],
                    transform=src.window_transform(chunk_win),
                    invert=True,
                    out_shape=tile_data.shape,
                )
                valid_mask = geom_mask & ~np.ma.getmaskarray(tile_data)
                if not valid_mask.any():
                    continue

                data = np.asarray(tile_data)
                valid_values = data[valid_mask]
                valid_values = valid_values[valid_values != 0]
                if valid_values.size == 0:
                    continue

                unique, chunk_counts = np.unique(valid_values, return_counts=True)
                yield {int(land_cover_class): int(count) for land_cover_class, count in zip(unique, chunk_counts)}

    def _get_intersecting_tile_ids(self, geometries: list) -> set[str]:
        bounds = GeometryCollection(geometries).bounds
        if any(math.isinf(value) for value in bounds):
            return set()

        minx, miny, maxx, maxy = bounds
        seen_tile_ids: set[str] = set()
        lon_step = math.floor(minx / 3) * 3
        while lon_step <= maxx:
            lat_step = math.floor(miny / 3) * 3
            while lat_step <= maxy:
                tile_id = get_worldcover_tile_id(lat_step + 1.5, lon_step + 1.5)
                tile_box = box(lon_step, lat_step, lon_step + 3, lat_step + 3)
                if any(geom.intersects(tile_box) for geom in geometries):
                    seen_tile_ids.add(tile_id)
                lat_step += 3
            lon_step += 3
        return seen_tile_ids
