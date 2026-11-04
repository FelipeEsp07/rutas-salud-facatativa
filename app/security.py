"""OAuth 2.0, flujo client_credentials con tokens JWT de corta duración (RNF-01)."""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from app.config import get_settings

# tokenUrl documenta en Swagger dónde se obtiene el token; no implica un login de usuario final.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", scopes={
    "rutas:generar": "Generar rutas de atención priorizadas",
    "auditoria:leer": "Consultar el registro de auditoría",
})


def autenticar_cliente(client_id: str, client_secret: str) -> set[str]:
    """Valida client_id/client_secret contra los clientes configurados. Devuelve los scopes otorgados."""
    settings = get_settings()
    cliente = settings.clients.get(client_id)
    if not cliente or cliente["secret"] != client_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="client_id o client_secret inválidos",
        )
    return cliente["scopes"]


def emitir_token(client_id: str, scopes: set[str]) -> tuple[str, int]:
    settings = get_settings()
    expira_en = settings.jwt_expire_minutes * 60
    expira = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": client_id,
        "scopes": sorted(scopes),
        "exp": expira,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expira_en


class TokenData:
    def __init__(self, client_id: str, scopes: set[str]):
        self.client_id = client_id
        self.scopes = scopes


def _decodificar(token: str) -> TokenData:
    settings = get_settings()
    credenciales_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise credenciales_invalidas
    client_id = payload.get("sub")
    scopes = set(payload.get("scopes", []))
    if not client_id:
        raise credenciales_invalidas
    return TokenData(client_id=client_id, scopes=scopes)


def requiere_scope(scope_requerido: str):
    """Fábrica de dependencias: exige que el token tenga el scope indicado."""

    def verificar(token: str = Depends(oauth2_scheme)) -> TokenData:
        datos = _decodificar(token)
        if scope_requerido not in datos.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El token no tiene el permiso requerido: {scope_requerido}",
            )
        return datos

    return verificar
