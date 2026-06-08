from supabase import create_client, Client
from app.config import settings

# Initialize client using anonymous key for standard operations
supabase_client: Client = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_KEY
)

# Initialize client using service role key for bypass RLS operations if needed
supabase_admin: Client = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY
)

def get_db():
    """Dependency helper to get the supabase client"""
    return supabase_client

def get_admin_db():
    """Dependency helper to get the supabase admin client (bypasses RLS)"""
    return supabase_admin
