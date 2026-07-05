from typing import Optional, Dict
from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str
    is_admin: bool = False

class UserResponse(UserBase):
    id: int
    is_active: bool
    is_admin: bool
    password_hash: str # Specified to show hash in management
    bearer_token: Optional[str] # Specified to show unencrypted token

    class Config:
        from_attributes = True

class LandCoverResponse(BaseModel):
    land_cover_class: int # rename to 'class' in response if needed

class LandCoverFractionsResponse(BaseModel):
    fractions: Dict[str, float]
