from supabase import create_client, Client
from app.config import get_settings

# service_role key로 생성 → RLS 우회 (백엔드 서버 전용)
_supabase_client: Client | None = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _supabase_client


def reset_supabase() -> Client:
    """stale connection 오류 발생 시 클라이언트 재생성"""
    global _supabase_client
    settings = get_settings()
    _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _supabase_client
