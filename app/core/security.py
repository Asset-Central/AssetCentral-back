"""
Envelope Encryption — AES-256-GCM

Esquema:
  Master Key (env var)  →  cifra el DEK de cada usuario  →  cifra las credenciales del broker

Nunca se almacena el Master Key ni el DEK en texto plano.
Una filtración de la DB sin el Master Key no expone ninguna credencial.
"""

import json
import os
import secrets
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings


def _master_key() -> bytes:
    key_hex = settings.master_encryption_key
    if len(key_hex) != 64:
        raise ValueError("MASTER_ENCRYPTION_KEY debe tener exactamente 64 chars hex (32 bytes)")
    return bytes.fromhex(key_hex)


def _aes_encrypt(key: bytes, plaintext: bytes) -> str:
    """Cifra con AES-256-GCM. Devuelve 'nonce:ciphertext' en base64."""
    nonce = secrets.token_bytes(12)  # 96 bits — recomendado para GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return b64encode(nonce).decode() + ":" + b64encode(ciphertext).decode()


def _aes_decrypt(key: bytes, token: str) -> bytes:
    """Descifra el resultado de _aes_encrypt."""
    nonce_b64, ct_b64 = token.split(":", 1)
    nonce = b64decode(nonce_b64)
    ciphertext = b64decode(ct_b64)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# --- API pública ---

def generate_dek() -> bytes:
    """Genera una Data Encryption Key aleatoria de 32 bytes."""
    return secrets.token_bytes(32)


def encrypt_dek(dek: bytes) -> str:
    """Cifra el DEK con el Master Key. Resultado almacenable en DB."""
    return _aes_encrypt(_master_key(), dek)


def decrypt_dek(dek_encrypted: str) -> bytes:
    """Descifra el DEK usando el Master Key."""
    return _aes_decrypt(_master_key(), dek_encrypted)


def encrypt_credentials(dek: bytes, credentials: dict) -> str:
    """Cifra las credenciales del broker con el DEK del usuario."""
    plaintext = json.dumps(credentials).encode()
    return _aes_encrypt(dek, plaintext)


def decrypt_credentials(dek: bytes, credentials_enc: str) -> dict:
    """Descifra las credenciales del broker con el DEK del usuario."""
    plaintext = _aes_decrypt(dek, credentials_enc)
    return json.loads(plaintext)
