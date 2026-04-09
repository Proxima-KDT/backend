import io
from openai import AsyncOpenAI
from app.config import get_settings

_client = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """OpenAI Whisper API로 오디오를 텍스트로 변환."""
    client = _get_client()

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename

    try:
        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ko",
            response_format="text",
        )
        return transcript.strip() if isinstance(transcript, str) else str(transcript).strip()
    except Exception:
        return ""
