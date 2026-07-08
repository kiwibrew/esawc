# ESA WorldCover 2021 v2 API Server

This application provides a web API to query ESA WorldCover 2021 v2 land cover data. It supports querying specific coordinates and calculating land cover fractions within a geodesic buffer (radius).

WorldCover 2021 v200 data © ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium

_Zanaga, D., Van De Kerchove, R., Daems, D., De Keersmaecker, W., Brockmann, C., Kirches, G., Wevers, J., Cartus, O., Santoro, M., Fritz, S., Lesiv, M., Herold, M., Tsendbazar, N.E., Xu, P., Ramoino, F., Arino, O., 2022. ESA WorldCover 10 m 2021 v200. https://doi.org/10.5281/zenodo.7254221_

## API Documentation

Access the interactive Swagger UI at `/docs`.

### Authentication
The API uses **Bearer Token** authentication. 
- Admin users do not have a bearer token by default; they manage the system.
- Regular users can view their unique bearer token on their profile/management page.
- In `/docs`, use the "Authorize" button to enter your bearer token.

### Endpoints

- **GET `/api/land-cover`**: 
  - Parameters: `lat`, `lon` (decimal degrees)
  - Returns: `{"class": 10}`
- **GET `/api/land-cover-fractions`**:
  - Parameters: `lat`, `lon`, `radius` (metres — **maximum 100,000 m / 100 km**)
  - Returns: A dictionary of class IDs and their decimal percentage coverage (e.g., `{"10": 0.7, "20": 0.3}`).
  - Requests with `radius > 100000` are rejected with HTTP 422.
- **POST `/api/land-cover-geojson`**:
  - Multipart upload with `geojson_file`
  - Returns `{"class": 10}` for a single GeoJSON `Point`
  - Returns a dictionary of class IDs and fractional coverage for other GeoJSON geometry types
  - If the uploaded GeoJSON does not overlap any available tile coverage, the request is rejected with HTTP 422 and `geojson does not have any coverage of any available tiles`

## Returned Data
ESA Worldcover Classes returned are:
```
10  Tree cover
20  Shrubland
30  Grassland
40  Cropland
50  Built-up
60  Bare / sparse vegetation
70  Snow and ice
80  Permanent water
90  Herbaceous wetland
95  Mangroves
100 Moss and lichen
```

## Land Cover Fractions Methodology

The `/api/land-cover-fractions` endpoint uses the following algorithm to compute land cover composition within a circular area:

1. **Geodesic buffer**: The query point is projected to an Azimuthal Equidistant (AEQD) coordinate system centred on that point. A circle of the requested radius (in metres) is drawn there, then reprojected back to WGS84. AEQD preserves distances from the centre, so the result is a true geodesic circle at any latitude.

2. **Tile identification**: The WGS84 bounding box of the circle is scanned in 3° steps to find every ESA WorldCover tile that the circle intersects. Each tile is downloaded from ESA's S3 bucket and cached locally on first use.

3. **Windowed reads**: Rather than loading each full ~2 GB tile into memory, only the small rectangular pixel window that overlaps the circle's bounding box is read from disk. Memory usage is therefore proportional to the query area, not the tile size — a 100 km radius query reads roughly 20,000 × 20,000 pixels (~400 MB) at most, compared to ~2 GB per full tile.

4. **Mosaic assembly**: The windowed pixel arrays from all intersecting tiles are placed into a single in-memory mosaic using pixel-offset arithmetic derived from each tile's affine transform.

5. **Geometry mask**: A pixel mask is applied so that only pixels whose centres fall inside the WGS84 circle polygon are counted.

6. **Fraction calculation**: Surviving pixel values are tallied by ESA WorldCover class number and converted to fractions of the total valid pixel count. The fractions are guaranteed to sum to exactly 1.0.

## Tile Caching Logic

To optimize performance and storage, the server implements an automated tile manager:
- **Identification**: Finds 3x3 degree tiles based on requested coordinates.
- **On-Demand Download**: Downloads tiles from ESA S3 only when needed.
- **Persistence**: Tiles are stored in `/app/data/tiles`.
- **Expiration**: 
  - Tile records are kept in SQLite.
  - Expiration is set to **one week** from the last use.
  - Expired tiles are automatically deleted from storage and database.

## User Management

### CLI User Management
For initial setup or command-line user management, use the `manage_users.py` script inside the application container.

#### Create Admin User
**Command:**
```bash
docker exec -it esawc-app python manage_users.py create <email> <password>
```

**Example:**
```bash
docker exec -it esawc-app python manage_users.py create admin@esawc.locnet.io YourSecretPassword
```

**What it does:**
- Checks if the email already exists in the database.
- Hashes the provided password using `passlib` (bcrypt).
- Creates a new user record with `is_admin=True` and `is_active=True`.
- Note: Admin users created via this script do not receive a Bearer Token by default.

#### Remove User
**Command:**
```bash
docker exec -it esawc-app python manage_users.py remove <email>
```

**Example:**
```bash
docker exec -it esawc-app python manage_users.py remove admin@esawc.locnet.io
```

**What it does:**
- Searches for the user by email in the database.
- Deletes the user record if found.

### Web Interface
Once an admin user is created, you can manage all users via the web UI at `http://localhost:8001/manage-users`.

- **Admin View**: Admins can create/delete users, toggle active status, grant admin rights, and regenerate bearer tokens.
- **User View**: Regular users can log in to view their own credentials and bearer token.

## Technologies Used

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Async Python)
- **Geospatial Processing**:
  - [Rasterio](https://rasterio.readthedocs.io/): For reading and sampling Cloud Optimized GeoTIFF (COG) tiles.
  - [Shapely](https://shapely.readthedocs.io/): For geometric operations and buffer creation.
  - [PyProj](https://pyproj4.github.io/pyproj/): For coordinate transformations and geodesic calculations.
- **Database**: [SQLite](https://www.sqlite.org/) with [SQLAlchemy 2.0](https://www.sqlalchemy.org/) (Async via `aiosqlite`).
- **Templating**: [Jinja2](https://jinja.palletsprojects.com/) for the User Management web interface.
- **Authentication**: Bearer Token for API and JWT-based sessions for the Web UI.
- **Deployment**: [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/) with a [Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/) sidecar.

## Architecture

The application follows a modular FastAPI structure:

- **Routers**: Handle API endpoints (`/api`) and Web UI/Auth routes (`/`).
- **Services**: Contain business logic, specifically the `WorldCoverService` which manages tile lifecycle and geospatial queries.
- **Models/Schemas**: SQLAlchemy ORM models and Pydantic validation schemas.
- **Database Layer**: Async SQLite connection handling and initialization.
- **Tile Caching**: Automated system to download, cache, and expire 3x3 degree GeoTIFF tiles from ESA's S3 bucket.

## Project Structure

```text
.
├── app/
│   ├── main.py           # FastAPI app entry point
│   ├── config.py         # Configuration and Environment variables
│   ├── database.py       # DB connection and session management
│   ├── dependencies.py   # Auth and DB dependencies
│   ├── models/           # SQLAlchemy ORM models
│   ├── routers/          # API and Auth/UI route modules
│   ├── services/         # Core business logic (Geospatial & Tiles)
│   └── templates/        # Jinja2 HTML templates
├── data_table_setup.sql  # Database schema for first-run initialization
├── docker-compose.yml    # Multi-container orchestration
├── Dockerfile            # Application container definition
├── manage_users.py       # CLI tool for bootstrapping admin users
└── requirements.txt      # Python dependencies
```

## Setup and Installation

### Docker (Recommended)

1. **Configure Environment**: Create a `.env` file (if needed) or set variables in `docker-compose.yml`.
   - `CLOUDFLARE_TUNNEL_TOKEN`: Your Cloudflare Zero Trust tunnel token.

2. **Start the containers**:
   ```bash
   docker-compose up -d
   ```

3. **Bootstrap Admin User**:
   ```bash
   docker exec -it esawc-app python manage_users.py create admin@esawc.locnet.io YourSecretPassword
   ```

The application will be available at `http://localhost:8001` (or via your Cloudflare tunnel URL).
