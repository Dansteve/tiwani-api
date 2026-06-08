from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_client
from app.models.chapter import Chapter, ChapterUpdate, PreferencesUpdate, Trigger, TriggerCreate
from app.routes.auth import get_current_user
from typing import List

router = APIRouter()

@router.get("/", response_model=List[Chapter])
async def list_chapters(current_user: dict = Depends(get_current_user)):
    try:
        response = supabase_client.table("chapters").select("*").eq("user_id", current_user["id"]).execute()
        return response.data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch chapters: {str(e)}"
        )

@router.post("/preferences", status_code=status.HTTP_200_OK)
async def update_preferences(
    preferences: PreferencesUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Saves/syncs the selected chapters and statuses from preferences & continuity steps.
    Deletes deselected ones and upserts selected ones.
    """
    try:
        user_id = current_user["id"]
        
        # 1. Fetch current chapters
        existing_query = supabase_client.table("chapters").select("name").eq("user_id", user_id).execute()
        existing_names = [item["name"] for item in existing_query.data] if existing_query.data else []

        selected_names = preferences.selected_chapters
        statuses = preferences.chapter_statuses

        # 2. Identify chapters to delete
        to_delete = [name for name in existing_names if name not in selected_names]
        if to_delete:
            supabase_client.table("chapters").delete().eq("user_id", user_id).in_("name", to_delete).execute()

        # 3. Upsert selected chapters
        upsert_payload = []
        for name in selected_names:
            status_val = statuses.get(name, "going_well")
            upsert_payload.append({
                "user_id": user_id,
                "name": name,
                "status": status_val
            })

        if upsert_payload:
            # We use supabase upsert matching on constraint (user_id, name)
            # Make sure this constraint exists in database schema
            supabase_client.table("chapters").upsert(
                upsert_payload, 
                on_conflict="user_id,name"
            ).execute()

        return {"status": "success", "message": "Preferences synced successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync preferences: {str(e)}"
        )

@router.put("/{chapter_name}/status", response_model=Chapter)
async def update_chapter_status(
    chapter_name: str,
    status_update: ChapterUpdate,
    current_user: dict = Depends(get_current_user)
):
    try:
        # Check if chapter exists for this user
        check = supabase_client.table("chapters").select("*").eq("name", chapter_name).eq("user_id", current_user["id"]).execute()
        if not check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chapter not found in user preferences"
            )

        response = supabase_client.table("chapters").update({
            "status": status_update.status
        }).eq("name", chapter_name).eq("user_id", current_user["id"]).execute()
        
        # Increment user's status_update_count
        profile_query = supabase_client.table("profiles").select("status_update_count").eq("id", current_user["id"]).single().execute()
        current_count = profile_query.data.get("status_update_count", 0) if profile_query.data else 0
        supabase_client.table("profiles").update({"status_update_count": current_count + 1}).eq("id", current_user["id"]).execute()

        return response.data[0]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update status: {str(e)}"
        )

# --- Triggers API ---

@router.get("/triggers", response_model=List[Trigger])
async def list_triggers(current_user: dict = Depends(get_current_user)):
    try:
        response = supabase_client.table("triggers").select("*").eq("user_id", current_user["id"]).execute()
        return response.data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch triggers: {str(e)}"
        )

@router.post("/triggers", response_model=Trigger, status_code=status.HTTP_201_CREATED)
async def add_trigger(
    trigger_data: TriggerCreate,
    current_user: dict = Depends(get_current_user)
):
    try:
        payload = trigger_data.model_dump(by_alias=False)
        payload["user_id"] = current_user["id"]

        response = supabase_client.table("triggers").insert(payload).execute()
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not save trigger"
            )
        return response.data[0]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add trigger: {str(e)}"
        )

@router.delete("/triggers/{trigger_id}", status_code=status.HTTP_200_OK)
async def delete_trigger(
    trigger_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        # Check authorization
        check = supabase_client.table("triggers").select("id").eq("id", trigger_id).eq("user_id", current_user["id"]).execute()
        if not check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trigger not found or unauthorized"
            )

        supabase_client.table("triggers").delete().eq("id", trigger_id).execute()
        return {"status": "success", "message": "Trigger deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete trigger: {str(e)}"
        )
