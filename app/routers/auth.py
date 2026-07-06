import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Form, Request
from fastapi.responses import RedirectResponse, HTMLResponse
import markdown
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt
from app.database import get_db
from app.models.models import User, CachedTile
from app.dependencies import pwd_context, get_current_active_user, get_current_admin_user, get_current_user
from app.config import settings
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["Auth & UI"])
templates = Jinja2Templates(directory="app/templates")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, user: Optional[User] = Depends(get_current_user)):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"user": user}
    )

@router.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == username))
    user = result.scalar_one_or_none()
    
    if not user or not pwd_context.verify(password, user.password_hash):
        return RedirectResponse(url="/?error=invalid_credentials", status_code=status.HTTP_303_SEE_OTHER)
    
    if not user.is_active:
         return RedirectResponse(url="/?error=inactive", status_code=status.HTTP_303_SEE_OTHER)

    access_token = create_access_token(data={"sub": user.email})
    
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/"
    )
    return response

@router.post("/token") # For FastAPI /docs login
async def login_for_access_token(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token", path="/", samesite="lax")
    return response

@router.get("/manage-users", response_class=HTMLResponse)
async def manage_users_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    if current_user.is_admin:
        result = await db.execute(select(User))
        users = result.scalars().all()
    else:
        users = [current_user]
    
    return templates.TemplateResponse(
        request=request, name="users.html", context={
            "current_user": current_user,
            "users": users
        }
    )

@router.post("/users/create")
async def create_user_route(
    email: str = Form(...),
    password: str = Form(...),
    is_admin: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User already exists")
    
    bearer_token = secrets.token_urlsafe(32) if not is_admin else None
    new_user = User(
        email=email,
        password_hash=pwd_context.hash(password),
        is_admin=is_admin,
        is_active=True,
        bearer_token=bearer_token
    )
    db.add(new_user)
    await db.commit()
    return RedirectResponse(url="/manage-users", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{user_id}/regen-token")
async def regen_token(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and not user.is_admin:
        user.bearer_token = secrets.token_urlsafe(32)
        await db.commit()
    return RedirectResponse(url="/manage-users", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{user_id}/toggle-active")
async def toggle_active(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.is_active = not user.is_active
        await db.commit()
    return RedirectResponse(url="/manage-users", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{user_id}/toggle-admin")
async def toggle_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.is_admin = not user.is_admin
        # If becoming admin, remove bearer token? The prompt implies only non-admins have tokens
        if user.is_admin:
            user.bearer_token = None
        else:
            user.bearer_token = secrets.token_urlsafe(32)
        await db.commit()
    return RedirectResponse(url="/manage-users", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        await db.delete(user)
        await db.commit()
    return RedirectResponse(url="/manage-users", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/tile-cache", response_class=HTMLResponse)
async def tile_cache_page(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    result = await db.execute(select(CachedTile))
    tiles = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="tile_cache.html", context={"tiles": tiles}
    )

@router.get("/app-docs", response_class=HTMLResponse)
async def app_docs(request: Request, current_user: User = Depends(get_current_active_user)):
    with open("README.md", "r") as f:
        content = markdown.markdown(f.read(), extensions=["fenced_code", "tables"])
    return templates.TemplateResponse(
        request=request, name="app_docs.html", context={"content": content}
    )
