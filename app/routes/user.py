from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_client, supabase_admin
from app.models.user import UserProfile, UserProfileUpdate, StatsUpdate
from app.routes.auth import get_current_user

router = APIRouter()

@router.get("/profile", response_model=UserProfile)
async def get_profile(current_user: dict = Depends(get_current_user)):
    try:
        # Fetch profile data from public.profiles
        response = supabase_client.table("profiles").select("*").eq("id", current_user["id"]).single().execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found"
            )
            
        return response.data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving profile: {str(e)}"
        )

@router.put("/profile", response_model=UserProfile)
async def update_profile(
    profile_update: UserProfileUpdate, 
    current_user: dict = Depends(get_current_user)
):
    try:
        # Filter out unset fields
        update_data = profile_update.model_dump(exclude_unset=True, by_alias=False)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No update parameters provided"
            )

        # Update profiles table
        response = supabase_client.table("profiles").update(update_data).eq("id", current_user["id"]).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile could not be updated"
            )
            
        return response.data[0]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating profile: {str(e)}"
        )

@router.post("/stats", response_model=UserProfile)
async def update_stats(
    stats: StatsUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update user usage statistics (counts)"""
    try:
        update_data = stats.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No stats provided to update"
            )
            
        response = supabase_client.table("profiles").update(update_data).eq("id", current_user["id"]).execute()
        return response.data[0]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.delete("/delete", status_code=status.HTTP_200_OK)
async def delete_account(current_user: dict = Depends(get_current_user)):
    try:
        # 1. Delete user auth record in Supabase (will cascade delete profiles if config is set, 
        # or we delete profile first to be clean)
        # Delete from profiles table
        supabase_admin.table("profiles").delete().eq("id", current_user["id"]).execute()
        
        # Delete auth user account using Admin client API
        supabase_admin.auth.admin.delete_user(current_user["id"])
        
        return {"status": "success", "message": "Account successfully deleted"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting account: {str(e)}"
        )
