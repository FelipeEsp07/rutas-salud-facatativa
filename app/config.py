"""Configuración de la aplicación, cargada desde variables de entorno (.env)."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    jwt_secret_key: str = "clave-de-desarrollo-no-usar-en-produccion"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30

    # client_id:client_secret:scope1,scope2;client_id:client_secret:scope1
    oauth_clients: str = "ebs-facatativa-01:secreto-demo-123:rutas:generar,auditoria:leer"

    database_url: str = "sqlite:///./auditoria.db"

    data_path: str = "data/veredas.json"

    @property
    def clients(self) -> dict:
        """Parsea OAUTH_CLIENTS a {client_id: {"secret": str, "scopes": set[str]}}."""
        result = {}
        for entry in self.oauth_clients.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            client_id, secret, scopes_raw = entry.split(":", 2)
            result[client_id] = {
                "secret": secret,
                "scopes": set(s.strip() for s in scopes_raw.split(",") if s.strip()),
            }
        return result


@lru_cache
def get_settings() -> Settings:
    return Settings()
