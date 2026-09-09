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
    # Pinned rather than configurable. Reading the algorithm from the
    # environment means a misconfiguration can weaken token verification, and
    # there is no deployment of this system that wants a different one.
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # Role enforcement.
    #
    # Defaults to True — fail closed. It was False, so that the prototype could
    # be driven without logging in, and the consequence was that an unset
    # environment variable silently promoted every anonymous request to state
    # admin: the fallback principal carries that role, so every RBAC guard in
    # the codebase became a no-op, including the audit trail and plate search.
    #
    # A surveillance platform must not have a default whose failure mode is
    # "everyone is an administrator". Local demonstration now opts out
    # explicitly with AUTH_ENABLED=false in .env, which is visible, deliberate,
    # and cannot happen by omission.
    auth_enabled: bool = True
    # Demonstration accounts, seeded only when seed_demo_users is true.
    #
    # The password is no longer a constant. A published default becomes the way
    # in the moment auth is switched on, which is exactly the transition that is
    # supposed to make the system safer. When this is left empty the seeder
    # generates a random password and logs it once at startup.
    demo_admin_email: str = "admin@sentinel.gujarat.gov.in"
    demo_admin_password: str = ""
    # Off unless explicitly requested, so a deployed instance does not quietly
    # grow accounts nobody asked for.
    seed_demo_users: bool = False

    # Addresses of reverse proxies whose X-Forwarded-For may be believed.
    # Empty means trust nothing and always use the socket address, which is the
    # safe default: an untrusted client that can set its own forwarded address
    # can give itself a fresh rate-limit bucket per request.
    trusted_proxies: str = ""

    # Seed the demonstration accounts. Off by default.

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
    @property
    def trusted_proxy_set(self) -> frozenset[str]:
        """Parsed TRUSTED_PROXIES, as a set for O(1) membership checks."""
        return frozenset(p.strip() for p in self.trusted_proxies.split(",") if p.strip())



@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
