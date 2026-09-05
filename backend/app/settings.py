from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase / Postgres
    database_url: str = "postgresql+psycopg://postgres:sentinel@localhost:5432/sentinel_db"
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_key: str = ""

    # JWT
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # Role enforcement. False lets the prototype be driven without logging in,
    # which is how the pipeline is demonstrated locally; a deployed instance sets
    # this true and every protected route then requires a bearer token.
    auth_enabled: bool = False
    # Seeded on first start so a deployed instance has working test credentials.
    # Override both before exposing the platform to anyone.
    demo_admin_email: str = "admin@sentinel.gujarat.gov.in"
    demo_admin_password: str = "sentinel-demo-2026"

    # Sentinel sandbox
    sentinel_host: str = "cctv.corp8.cloud"
    sentinel_cdn_host: str = "cctv.corp8.cloud"
    sentinel_ip: str = "103.250.160.189"
    sentinel_rtsp_port: int = 8554
    sentinel_whep_port: int = 8889
    sentinel_user_email: str = ""
    sentinel_user_password: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Storage
    evidence_crop_dir: str = "./evidence_crops"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
