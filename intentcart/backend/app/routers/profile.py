from fastapi import APIRouter, Depends

from app.auth import current_user
from app.dependencies import get_store, profile_for
from app.memory.store import Store
from app.schemas import Profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=Profile)
async def get_profile(uid: str = Depends(current_user), store: Store = Depends(get_store)):
    return await profile_for(store, uid)


@router.put("", response_model=Profile)
async def save_profile(
    profile: Profile, uid: str = Depends(current_user), store: Store = Depends(get_store)
):
    await store.put(uid, "profile", "current", profile.model_dump(mode="json"))
    return profile
