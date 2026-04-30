import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import engine, Base
from routers import auth, patterns, favorites, admin
from seed import seed_demo_data

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("data", exist_ok=True)
    os.makedirs("uploads", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    seed_demo_data()
    yield


app = FastAPI(title="PixelCraft API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(patterns.router, prefix="/api/patterns", tags=["patterns"])
app.include_router(favorites.router, prefix="/api/favorites", tags=["favorites"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Local-dev convenience: serve the frontend SPA from the backend ────────────
# In production, nginx handles static files. In local dev, visit http://localhost:8000
if _FRONTEND_DIR.is_dir():
    @app.get("/funlab-logo.jpeg", include_in_schema=False)
    def _logo():
        return FileResponse(_FRONTEND_DIR / "funlab-logo.jpeg", media_type="image/jpeg")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(_: str):
        return FileResponse(_FRONTEND_DIR / "index.html", media_type="text/html")
