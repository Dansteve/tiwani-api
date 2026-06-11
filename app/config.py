import os
from typing import List
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "Tiwani API"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    
    # Supabase config
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    
    # Postgres database for SQLAlchemy
    DATABASE_URL: str = ""

    # CORS allowed origins as a comma-separated string from the environment.
    # Defaults to the local app and website dev origins. Read the parsed list
    # via the cors_allow_origins property.
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:5173,http://localhost:5174"

    @computed_field
    @property
    def cors_allow_origins(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
