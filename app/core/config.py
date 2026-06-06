from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # 64 chars hex = 32 bytes = clave AES-256
    master_encryption_key: str

    frontend_url: str = "http://localhost:5173"
    environment: str = "development"

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"


settings = Settings()
