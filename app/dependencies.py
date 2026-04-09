import logging
import httpx
from functools import lru_cache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.config import get_settings

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


@lru_cache()
def _get_jwks() -> dict:
    """Supabase JWKS 공개키를 가져온다 (프로세스 생애주기 동안 캐시)."""
    settings = get_settings()
    url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """JWT 토큰을 디코딩하여 현재 사용자 정보를 반환한다."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 없습니다.",
        )
    settings = get_settings()
    token = credentials.credentials

    try:
        # ES256(신규 JWT Signing Keys) 및 HS256(레거시) 모두 지원
        try:
            jwks = _get_jwks()
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
        except JWTError:
            # JWKS 검증 실패 시 레거시 HS256 secret으로 재시도
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
    except JWTError as e:
        logger.error("JWT decode error: %s | token_prefix: %s", str(e), token[:20])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 인증 토큰입니다.",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰에 사용자 정보가 없습니다.",
        )

    role = payload.get("user_metadata", {}).get("role", "student")

    return {"id": user_id, "role": role, "email": payload.get("email")}


async def get_current_teacher(user: dict = Depends(get_current_user)) -> dict:
    """강사 전용 — role이 teacher가 아니면 403"""
    if user["role"] != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="강사 권한이 필요합니다.",
        )
    return user


async def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    """관리자 전용 — role이 admin이 아니면 403"""
    if user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다.",
        )
    return user


async def get_teacher_or_admin(user: dict = Depends(get_current_user)) -> dict:
    """강사 또는 관리자 — 둘 다 아니면 403"""
    if user["role"] not in ("teacher", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="강사 또는 관리자 권한이 필요합니다.",
        )
    return user
