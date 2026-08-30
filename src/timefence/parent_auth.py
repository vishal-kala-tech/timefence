import hashlib
import json
import secrets
from pathlib import Path

COOKIE_NAME = "tf_parent"
PARENT_FILE = "parent.json"
_PBKDF2_ROUNDS = 120_000


def parent_path(app_dir):
    return Path(app_dir) / "config" / PARENT_FILE


def load_parent(app_dir):
    path = parent_path(app_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_parent(app_dir, data):
    path = parent_path(app_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _hash_pin(pin, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(pin).encode("utf-8"),
        bytes.fromhex(salt_hex),
        _PBKDF2_ROUNDS,
    ).hex()


def has_pin(app_dir):
    data = load_parent(app_dir)
    return bool(data.get("pin_hash") and data.get("salt") and data.get("token"))


def set_pin(app_dir, pin):
    pin = str(pin or "").strip()
    if len(pin) < 4:
        raise ValueError("PIN must be at least 4 characters")
    salt = secrets.token_hex(16)
    token = secrets.token_hex(32)
    _save_parent(
        app_dir,
        {
            "salt": salt,
            "pin_hash": _hash_pin(pin, salt),
            "token": token,
        },
    )
    return token


def unlock(app_dir, pin):
    data = load_parent(app_dir)
    salt = data.get("salt")
    expected = data.get("pin_hash")
    token = data.get("token")
    if not (salt and expected and token):
        raise ValueError("No parent PIN is set yet")
    actual = _hash_pin(str(pin or "").strip(), salt)
    if not secrets.compare_digest(actual, expected):
        raise ValueError("Wrong PIN")
    return token


def valid_token(app_dir, token):
    if not token:
        return False
    stored = str(load_parent(app_dir).get("token") or "")
    if not stored:
        return False
    return secrets.compare_digest(str(token), stored)


def cookie_header(token=None, clear=False):
    if clear or not token:
        return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
    return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict"


def parse_cookie_header(header):
    out = {}
    for part in str(header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = value.strip()
    return out
