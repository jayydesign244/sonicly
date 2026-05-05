from fastapi import APIRouter, HTTPException, status
from models.schemas import UserCreate, UserLogin, UserOut, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory store for prototype — replace with a real DB in production
_users: list[dict] = []
_next_id = 1


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: UserCreate):
    global _next_id
    if any(u["email"] == payload.email for u in _users):
        raise HTTPException(status_code=400, detail="Email already registered")

    user = {"id": _next_id, "name": payload.name, "email": payload.email}
    _users.append(user)
    _next_id += 1

    return TokenResponse(
        access_token=f"mock_token_{user['id']}",
        user=UserOut(**user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin):
    user = next((u for u in _users if u["email"] == payload.email), None)
    if not user:
        # Auto-create for prototype convenience
        global _next_id
        user = {"id": _next_id, "name": payload.email.split("@")[0], "email": payload.email}
        _users.append(user)
        _next_id += 1

    return TokenResponse(
        access_token=f"mock_token_{user['id']}",
        user=UserOut(**user),
    )


@router.get("/me", response_model=UserOut)
async def me():
    if not _users:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserOut(**_users[0])
