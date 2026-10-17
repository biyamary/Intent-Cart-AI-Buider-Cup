from fastapi import HTTPException, Request

from app.memory.store import Store
from app.schemas import Profile


def get_store(request: Request) -> Store:
    return request.app.state.store


async def profile_for(store: Store, uid: str) -> Profile:
    return Profile.model_validate(await store.get(uid, "profile", "current") or {})


async def owned_record(store: Store, uid: str, collection: str, key: str) -> dict:
    record = await store.get(uid, collection, key)
    if record is None:
        raise HTTPException(404, "Record not found.")
    return record
