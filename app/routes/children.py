from fastapi import APIRouter, Depends, HTTPException, status
from app.database import supabase_client
from app.models.child import Child, ChildCreate, ChildUpdate
from app.routes.auth import get_current_user
from typing import List

router = APIRouter()

@router.get("/", response_model=List[Child])
async def list_children(current_user: dict = Depends(get_current_user)):
    try:
        response = supabase_client.table("children").select("*").eq("user_id", current_user["id"]).execute()
        return response.data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch children: {str(e)}"
        )

@router.post("/", response_model=Child, status_code=status.HTTP_201_CREATED)
async def add_child(
    child_data: ChildCreate,
    current_user: dict = Depends(get_current_user)
):
    try:
        new_child = child_data.model_dump(by_alias=False)
        new_child["user_id"] = current_user["id"]
        
        response = supabase_client.table("children").insert(new_child).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not save child details"
            )
        return response.data[0]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add child: {str(e)}"
        )

@router.put("/{child_id}", response_model=Child)
async def update_child(
    child_id: str,
    child_update: ChildUpdate,
    current_user: dict = Depends(get_current_user)
):
    try:
        update_data = child_update.model_dump(exclude_unset=True, by_alias=False)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No update parameters provided"
            )
            
        # Verify ownership
        check = supabase_client.table("children").select("id").eq("id", child_id).eq("user_id", current_user["id"]).execute()
        if not check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Child record not found or unauthorized access"
            )

        response = supabase_client.table("children").update(update_data).eq("id", child_id).execute()
        return response.data[0]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update child: {str(e)}"
        )

@router.delete("/{child_id}", status_code=status.HTTP_200_OK)
async def delete_child(
    child_id: str,
    current_user: dict = Depends(get_current_user)
):
    try:
        # Verify ownership
        check = supabase_client.table("children").select("id").eq("id", child_id).eq("user_id", current_user["id"]).execute()
        if not check.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Child record not found or unauthorized access"
            )

        supabase_client.table("children").delete().eq("id", child_id).execute()
        return {"status": "success", "message": "Child record deleted"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete child: {str(e)}"
        )
