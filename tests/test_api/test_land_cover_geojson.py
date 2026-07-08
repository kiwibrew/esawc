from io import BytesIO
from types import SimpleNamespace

import numpy as np
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.database import get_db
from app.dependencies import get_current_active_user
from app.main import app
from app.services.worldcover import WorldCoverService


def _write_test_raster(path):
    data = np.array(
        [
            [10, 20, 30, 40, 50, 60],
            [10, 20, 30, 40, 50, 60],
            [70, 80, 90, 95, 100, 10],
            [70, 80, 90, 95, 100, 10],
            [20, 20, 30, 30, 40, 40],
            [20, 20, 30, 30, 40, 40],
        ],
        dtype=np.uint8,
    )
    transform = from_origin(0, 6, 1, 1)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)


async def override_get_db():
    yield object()


def override_get_current_active_user():
    return SimpleNamespace(email="user@example.com", is_admin=False)


def test_land_cover_geojson_point_returns_class(tmp_path, monkeypatch):
    raster_path = tmp_path / "worldcover.tif"
    _write_test_raster(raster_path)

    async def fake_get_tile_path(self, _lat, _lon):
        return str(raster_path)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    monkeypatch.setattr(WorldCoverService, "get_tile_path", fake_get_tile_path)

    geojson = b'{"type":"Point","coordinates":[0.5,5.5]}'

    try:
        client = TestClient(app)
        response = client.post(
            "/api/land-cover-geojson",
            files={"geojson_file": ("point.geojson", BytesIO(geojson), "application/geo+json")},
        )
        assert response.status_code == 200
        assert response.json() == {"class": 10}
    finally:
        app.dependency_overrides.clear()


def test_land_cover_geojson_polygon_returns_fractions(tmp_path, monkeypatch):
    raster_path = tmp_path / "worldcover.tif"
    _write_test_raster(raster_path)

    async def fake_get_tile_path(self, _lat, _lon):
        return str(raster_path)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    monkeypatch.setattr(WorldCoverService, "get_tile_path", fake_get_tile_path)

    geojson = (
        b'{"type":"Polygon","coordinates":[[[0,6],[2,6],[2,4],[0,4],[0,6]]]}'
    )

    try:
        client = TestClient(app)
        response = client.post(
            "/api/land-cover-geojson",
            files={"geojson_file": ("polygon.geojson", BytesIO(geojson), "application/geo+json")},
        )
        assert response.status_code == 200
        assert response.json() == {"10": 0.5, "20": 0.5}
    finally:
        app.dependency_overrides.clear()


def test_land_cover_geojson_returns_422_without_tile_coverage(tmp_path, monkeypatch):
    raster_path = tmp_path / "worldcover.tif"
    _write_test_raster(raster_path)

    async def fake_get_tile_path(self, _lat, _lon):
        return str(raster_path)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = override_get_current_active_user
    monkeypatch.setattr(WorldCoverService, "get_tile_path", fake_get_tile_path)

    geojson = (
        b'{"type":"Polygon","coordinates":[[[20,20],[21,20],[21,21],[20,21],[20,20]]]}'
    )

    try:
        client = TestClient(app)
        response = client.post(
            "/api/land-cover-geojson",
            files={"geojson_file": ("outside.geojson", BytesIO(geojson), "application/geo+json")},
        )
        assert response.status_code == 422
        assert response.json() == {
            "detail": "geojson does not have any coverage of any available tiles"
        }
    finally:
        app.dependency_overrides.clear()
