from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ChildBase(BaseModel):
    first_name: str = Field(..., alias="firstName")
    last_name: str = Field(..., alias="lastName")
    age_range: str = Field(..., alias="ageRange")  # e.g., '2-4'
    support_needs: str = Field(..., alias="supportNeeds")  # e.g., 'low', 'medium', 'high'

    model_config = {
        "populate_by_name": True
    }

class ChildCreate(ChildBase):
    pass

class ChildUpdate(BaseModel):
    first_name: Optional[str] = Field(None, alias="firstName")
    last_name: Optional[str] = Field(None, alias="lastName")
    age_range: Optional[str] = Field(None, alias="ageRange")
    support_needs: Optional[str] = Field(None, alias="supportNeeds")

    model_config = {
        "populate_by_name": True
    }

class Child(ChildBase):
    id: str
    user_id: str
    created_at: datetime

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }
