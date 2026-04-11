from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings

# 라우터 임포트
from app.routers import (
    auth,
    attendance,
    curriculum,
    equipment,
    interview,
    jobs,
    problems,
    submissions,
    teacher,
    users,
    voice,
    admin,
    counseling_manage,
)
from app.routers import (
    subjects,
    assessments,
    assignments,
    counseling,
    questions,
    rooms,
    profile,
    skills,
    ai_agent,
)

settings = get_settings()

app = FastAPI(
    title="EduPilot API",
    description="AI 기반 IT교육 통합 관리 플랫폼 백엔드",
    version="1.0.0",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(profile.router)
app.include_router(curriculum.router)
app.include_router(subjects.router)
app.include_router(problems.router)
app.include_router(submissions.router)
app.include_router(assessments.router)
app.include_router(assignments.router)
app.include_router(attendance.router)
app.include_router(equipment.router)
app.include_router(rooms.router)
app.include_router(counseling.router)
app.include_router(interview.router)
app.include_router(voice.router)
app.include_router(jobs.router)
app.include_router(questions.router)
app.include_router(skills.router)
app.include_router(teacher.router)
app.include_router(admin.router)
app.include_router(counseling_manage.router)
app.include_router(ai_agent.router)


@app.get("/")
async def root():
    return {"message": "EduPilot API is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}
