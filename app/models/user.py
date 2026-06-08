from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class UserRegister(BaseModel):
    first_name: str = Field(..., alias="firstName")
    last_name: str = Field(..., alias="lastName")
    email: EmailStr
    password: str

    model_config = {
        "populate_by_name": True
    }

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str

class UserProfile(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    login_count: int = 0
    status_update_count: int = 0
    preparation_reuse_count: int = 0
    created_at: datetime

    model_config = {
        "from_attributes": True
    }

class UserProfileUpdate(BaseModel):
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")

    model_config = {
        "populate_by_name": True
    }

class StatsUpdate(BaseModel):
    login_count: Optional[int] = None
    status_update_count: Optional[int] = None
    preparation_reuse_count: Optional[int] = None
