from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.database import get_db
from app.models.models import User
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_COOKIE_NAME = "esawc_session"

# For Web UI Login (Cookies/Session would be better but keeping it simple with JWT if needed, 
# or just use the database session if possible. The prompt says "Bearer token authentication").
# API uses Bearer Token. Web UI will need some way to know who is logged in.

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)
bearer_header = APIKeyHeader(name="Authorization", auto_error=False)

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    # Check Authorization header first
    auth_header = request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    
    # If no token from Authorization header, check cookie
    if not token:
        cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
        if cookie_token and cookie_token.startswith("Bearer "):
            token = cookie_token[7:]

    if not token:
        return None
    
    # Check if token is a bearer token from DB
    # The prompt says "The user management page should also allow the admin to regenerate the bearer token for any user."
    # and "it will use bearer token authentication."
    
    # First try as a direct bearer token match in DB
    result = await db.execute(select(User).where(User.bearer_token == token))
    user = result.scalar_one_or_none()
    if user:
        return user
    
    # If not found, it might be a JWT session token (for the Web UI)
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None
    except JWTError:
        return None
        
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    return user

async def get_current_active_user(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user)
) -> User:
    if not current_user:
        # API routes (under /api) return JSON 401; UI routes redirect to login
        if request.url.path.startswith("/api"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/"})
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_admin_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user
