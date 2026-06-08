from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from app.database import supabase_client, supabase_admin
from app.models.user import UserRegister, UserLogin, Token, UserProfile
from gotrue.errors import AuthApiError
from typing import Optional

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    Dependency to validate the Bearer token against Supabase Auth.
    Returns the Supabase user details dictionary.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.split(" ")[1]
    try:
        # Validate token and retrieve user details from Supabase auth
        response = supabase_client.auth.get_user(token)
        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid active session or token"
            )
        return {
            "id": response.user.id,
            "email": response.user.email
        }
    except AuthApiError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal auth validation error: {str(e)}"
        )

@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
async def signup(user_data: UserRegister):
    try:
        # 1. Sign up user in Supabase Auth
        auth_response = supabase_client.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password
        })

        if not auth_response or not auth_response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create user account"
            )

        user_id = auth_response.user.id

        # 2. Insert profile information into the public.profiles table using admin client
        # (This avoids RLS insert blocks before the user session is fully active)
        profile_data = {
            "id": user_id,
            "email": user_data.email,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "login_count": 1,
            "status_update_count": 0,
            "preparation_reuse_count": 0
        }
        
        # Insert into public.profiles
        supabase_admin.table("profiles").insert(profile_data).execute()

        # Extract access token
        access_token = auth_response.session.access_token if auth_response.session else ""

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user_id
        }

    except AuthApiError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database or signup error: {str(e)}")

@router.post("/login", response_model=Token)
async def login(credentials: UserLogin):
    try:
        # 1. Sign in with password using Supabase auth
        auth_response = supabase_client.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password
        })

        if not auth_response or not auth_response.session or not auth_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        user_id = auth_response.user.id

        # 2. Increment login count in database using service role (bypass RLS safety)
        # Fetch current count
        profile_query = supabase_admin.table("profiles").select("login_count").eq("id", user_id).single().execute()
        current_count = profile_query.data.get("login_count", 0) if profile_query.data else 0

        # Update login count
        supabase_admin.table("profiles").update({"login_count": current_count + 1}).eq("id", user_id).execute()

        return {
            "access_token": auth_response.session.access_token,
            "token_type": "bearer",
            "user_id": user_id
        }

    except AuthApiError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or password credentials")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
