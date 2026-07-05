# ESA WorldCover 2021 v2 API Server

This application provides a web API to query ESA WorldCover 2021 v2 land cover data. It supports querying specific coordinates and calculating land cover fractions within a geodesic buffer (radius).

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
  - Parameters: `lat`, `lon`, `radius` (meters)
  - Returns: A dictionary of class IDs and their decimal percentage coverage (e.g., `{"10": 0.7, "20": 0.3}`).

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
