import rasterio
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

from app.services.worldcover import WorldCoverService


def _write_raster(path, data, *, west: float, north: float, pixel_size: float):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=from_origin(west, north, pixel_size, pixel_size),
    ) as dst:
        dst.write(data, 1)


@pytest.mark.asyncio
async def test_counts_are_aggregated_across_chunks(tmp_path, monkeypatch):
    import numpy as np

    raster_path = tmp_path / "tile.tif"
    data = np.array(
        [
            [10, 10, 20, 20],
            [10, 10, 20, 20],
            [30, 30, 40, 40],
            [30, 30, 40, 40],
        ],
        dtype=np.uint8,
    )
    _write_raster(raster_path, data, west=0, north=2, pixel_size=0.5)

    service = WorldCoverService(object())
    monkeypatch.setattr(service, "WINDOW_CHUNK_SIZE", 2)

    async def fake_get_tile_path(self, _lat, _lon):
        return str(raster_path)

    monkeypatch.setattr(WorldCoverService, "get_tile_path", fake_get_tile_path)

    counts = await service._get_land_cover_counts_for_geometries(
        [box(0, 0, 2, 2)],
        raise_on_empty=True,
    )

    assert counts == {10: 4, 20: 4, 30: 4, 40: 4}


@pytest.mark.asyncio
async def test_counts_are_aggregated_across_multiple_tiles(tmp_path, monkeypatch):
    import numpy as np

    south_raster_path = tmp_path / "south_tile.tif"
    north_raster_path = tmp_path / "north_tile.tif"

    south_data = np.full((6, 6), 10, dtype=np.uint8)
    north_data = np.full((6, 6), 20, dtype=np.uint8)

    _write_raster(south_raster_path, south_data, west=105, north=48, pixel_size=0.5)
    _write_raster(north_raster_path, north_data, west=105, north=51, pixel_size=0.5)

    service = WorldCoverService(object())
    monkeypatch.setattr(service, "WINDOW_CHUNK_SIZE", 2)

    async def fake_get_tile_path(self, lat, _lon):
        if lat < 48:
            return str(south_raster_path)
        return str(north_raster_path)

    monkeypatch.setattr(WorldCoverService, "get_tile_path", fake_get_tile_path)

    counts = await service._get_land_cover_counts_for_geometries(
        [box(106, 47, 107, 49)],
        raise_on_empty=True,
    )

    assert counts == {10: 4, 20: 4}
