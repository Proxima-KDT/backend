from supabase import create_client, Client
from app.config import get_settings

# 프로세스 생애주기 동안 단일 클라이언트 재사용 (매 요청마다 생성하면 HTTP 세션 초기화 오버헤드 발생)
_supabase_client: Client | None = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _supabase_client
