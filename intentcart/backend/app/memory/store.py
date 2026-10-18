import asyncio
from copy import deepcopy
from typing import Protocol


class Store(Protocol):
    async def get(self, uid: str, collection: str, key: str) -> dict | None: ...
    async def put(self, uid: str, collection: str, key: str, value: dict) -> None: ...
    async def list(self, uid: str, collection: str) -> list[dict]: ...
    async def get_evidence(self, key: str) -> dict | None: ...
    async def put_evidence(self, key: str, value: dict) -> None: ...


class MemoryStore:
    """Development only: single process, resets on restart, never shared between users."""

    def __init__(self):
        self._data: dict[tuple[str, str, str], dict] = {}
        self._evidence: dict[str, dict] = {}

    async def get_evidence(self, key):
        return deepcopy(self._evidence.get(key))

    async def put_evidence(self, key, value):
        self._evidence[key] = deepcopy(value)

    async def get(self, uid, collection, key):
        return deepcopy(self._data.get((uid, collection, key)))

    async def put(self, uid, collection, key, value):
        self._data[(uid, collection, key)] = deepcopy(value)

    async def list(self, uid, collection):
        return deepcopy([v for (u, c, _), v in self._data.items() if (u, c) == (uid, collection)])


class FirestoreStore:
    """Admin SDK adapter. API token verification establishes uid; clients cannot choose it."""

    def __init__(self, project: str):
        from google.cloud import firestore

        self.client = firestore.Client(project=project)

    def _ref(self, uid, collection, key):
        user = self.client.collection("users").document(uid)
        return user if collection == "profile" else user.collection(collection).document(key)

    async def get_evidence(self, key):
        ref = self.client.collection("food_evidence").document(key)
        snap = await asyncio.to_thread(ref.get)
        return snap.to_dict() if snap.exists else None

    async def put_evidence(self, key, value):
        ref = self.client.collection("food_evidence").document(key)
        await asyncio.to_thread(ref.set, value)

    async def get(self, uid, collection, key):
        snap = await asyncio.to_thread(self._ref(uid, collection, key).get)
        return snap.to_dict() if snap.exists else None

    async def put(self, uid, collection, key, value):
        await asyncio.to_thread(self._ref(uid, collection, key).set, value)

    async def list(self, uid, collection):
        ref = self.client.collection("users").document(uid).collection(collection)
        return await asyncio.to_thread(lambda: [snap.to_dict() for snap in ref.stream()])
