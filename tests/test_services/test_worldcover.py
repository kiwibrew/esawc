import pytest
import math
from app.services.worldcover import get_worldcover_tile_id, get_worldcover_url

def test_tile_id_calculation():
    # Example provided by user: S48E036 covers 36°E–39°E and 48°S–45°S
    # My logic: 
    # lat = -46.5, lon = 37.5
    # tile_lat = floor(-46.5 / 3) * 3 = -16 * 3 = -48
    # tile_lon = floor(37.5 / 3) * 3 = 12 * 3 = 36
    # -> S48E036
    assert get_worldcover_tile_id(-46.5, 37.5) == "S48E036"
    
    # Another example: -41.3, 174.8
    # tile_lat = floor(-41.3 / 3) * 3 = -14 * 3 = -42
    # tile_lon = floor(174.8 / 3) * 3 = 58 * 3 = 174
    # -> S42E174
    assert get_worldcover_tile_id(-41.3, 174.8) == "S42E174"

def test_url_generation():
    tile_id = "S42E174"
    url = get_worldcover_url(tile_id)
    assert url == "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_S42E174_Map.tif"
