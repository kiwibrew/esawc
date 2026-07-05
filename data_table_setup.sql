CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    bearer_token TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    is_admin BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME
);

CREATE INDEX idx_users_email ON users (email);

CREATE TABLE cached_tiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tile_id TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    last_used_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);

CREATE INDEX idx_cached_tiles_expires_at ON cached_tiles (expires_at);
