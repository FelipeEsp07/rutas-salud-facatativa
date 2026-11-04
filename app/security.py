"""OAuth 2.0, flujo client_credentials con tokens JWT de corta duración (RNF-01)."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import obtener_usuario_por_username

# tokenUrl documenta en Swagger dónde se obtiene el token; no implica un login de usuario final.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", scopes={
    "rutas:generar": "Generar rutas de atención priorizadas",
    "auditoria:leer": "Consultar el registro de auditoría",
})

# RF-09/RF-10: permisos según el rol elegido al crear la cuenta (POST /usuarios).
SCOPES_POR_ROL: dict[str, set[str]] = {
    "coordinador": {"rutas:generar"},
    "administrador": {"rutas:generar", "auditoria:leer"},
}
_ITERACIONES_HASH = 200_000


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 con sal aleatoria. Sin dependencias nuevas (solo librería estándar)."""
    sal = secrets.token_hex(16)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal.encode("utf-8"), _ITERACIONES_HASH)
    return f"{sal}${derivado.hex()}"


def verificar_password(password: str, hash_guardado: str) -> bool:
    try:
        sal, esperado = hash_guardado.split("$", 1)
    except ValueError:
        return False
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal.encode("utf-8"), _ITERACIONES_HASH)
    return secrets.compare_digest(derivado.hex(), esperado)


def autenticar_cliente(sesion: Session, client_id: str, client_secret: str) -> set[str]:
    """
    Valida client_id/client_secret contra dos fuentes, en este orden:
    1. Los clientes de sistema configurados en OAUTH_CLIENTS (.env) — pensados para
       integraciones servicio-a-servicio, como el cliente de demostración.
    2. Las cuentas creadas con POST /usuarios, guardadas en la base de datos.
    Devuelve los scopes otorgados, o rechaza con 401 si no coincide con ninguna.
    """
    settings = get_settings()
    cliente = settings.clients.get(client_id)
    if cliente and cliente["secret"] == client_secret:
        return cliente["scopes"]

    usuario = obtener_usuario_por_username(sesion, client_id)
    if usuario and verificar_password(client_secret, usuario.password_hash):
        return SCOPES_POR_ROL.get(usuario.rol, set())

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Usuario o contraseña inválidos",
    )


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
