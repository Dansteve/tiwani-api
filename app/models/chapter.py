from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime

class ChapterBase(BaseModel):
    name: str  # e.g., 'Social & community'
    status: str = "going_well"  # e.g., 'going_well', 'needs_support'

class ChapterCreate(ChapterBase):
    pass

class ChapterUpdate(BaseModel):
    status: str

class Chapter(ChapterBase):
    id: str
    user_id: str
    created_at: datetime

    model_config = {
        "from_attributes": True
    }

class TriggerBase(BaseModel):
    chapter: str
    participation_level: str = Field(..., alias="participationLevel")  # 'observe', 'partial', 'participate'
    trigger: str
    impact: str
    is_custom: bool = Field(False, alias="isCustom")

    model_config = {
        "populate_by_name": True
    }

class TriggerCreate(TriggerBase):
    pass

class Trigger(TriggerBase):
    id: str
    user_id: str
    created_at: datetime

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }

# Bulk preferences save
class PreferencesUpdate(BaseModel):
    selected_chapters: List[str] = Field(..., alias="selectedChapters")
    chapter_statuses: Dict[str, str] = Field(..., alias="chapterStatuses")

    model_config = {
        "populate_by_name": True
    }
