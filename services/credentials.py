"""Manage one plugin-load credential session without environment fallbacks."""

import ctypes
import os
from pathlib import Path
import threading
from ctypes import wintypes


class CredentialError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.error_code = code
        self.attempts = 1


class CredentialSession:
    def __init__(self):
        self._lock = threading.RLock()
        self._key = ""
        self._generation = 0

    @property
    def ready(self):
        with self._lock:
            return bool(self._key)

    def reset(self):
        with self._lock:
            self._key = ""
            self._generation += 1
            return self._generation

    def activate(self, key, generation):
        with self._lock:
            if generation != self._generation:
                raise CredentialError("MODEL_AUTH_FAILED", 'Configuration changed. Verify again.')
            self._key = key

    def require_key(self):
        with self._lock:
            if not self._key:
                raise CredentialError("MODEL_AUTH_FAILED", 'Configure and verify an API Key first.')
            return self._key

    def snapshot(self):
        with self._lock:
            return self.require_key(), self._generation

    def check_generation(self, generation):
        with self._lock:
            if generation != self._generation or not self._key:
                raise CredentialError("MODEL_AUTH_FAILED", 'Key configuration changed. Start the call again.')


session = CredentialSession()


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, decrypt=False):
    if os.name != "nt":
        raise OSError("Protected storage is unavailable on this platform")
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)


class ProtectedKeyStore:
    def __init__(self, directory):
        self.path = Path(directory) / "api-key.dpapi"

    def save(self, key):
        encrypted = _dpapi(key.encode("utf-8"))
        if _dpapi(encrypted, decrypt=True).decode("utf-8") != key:
            raise OSError("Protected storage verification failed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_bytes(encrypted)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(".tmp").unlink(missing_ok=True)


def service_error(status=0, code=""):
    code = str(code).lower()
    if status == 401 or "invalidapikey" in code or "invalid_api_key" in code:
        return CredentialError("MODEL_AUTH_FAILED", 'The API Key is invalid or has expired. Configure it again.')
    if status in (402, 429) or any(word in code for word in ("quota", "balance", "arrear", "ratelimit")):
        return CredentialError("MODEL_QUOTA_FAILED", 'Insufficient quota or rate limit reached. Check balance, quota and request frequency.')
    if status == 404 or any(word in code for word in ("modelnotfound", "model_not_found", "model.not")):
        return CredentialError("MODEL_UNAVAILABLE", 'The requested model is unavailable. Check its name and activation status.')
    if status == 403 or "permission" in code or "accessdenied" in code:
        return CredentialError("MODEL_PERMISSION_FAILED", 'This key cannot access the model. Check service authorization.')
    if status in (408, 504) or not status:
        return CredentialError("MODEL_NETWORK_FAILED", 'Connection failed or timed out. Check the network and retry.')
    return CredentialError("MODEL_SERVER_FAILED", 'The model service request failed. Try again later.')


def check_response(response):
    if response.status_code >= 400:
        try:
            body = response.json()
            error = body.get("error", body)
            code = error.get("code", "") if isinstance(error, dict) else ""
        except (ValueError, TypeError, AttributeError):
            code = ""
        raise service_error(response.status_code, code)


def model_post(url, **kwargs):
    """Read credentials for each call and reject responses from expired sessions."""
    import requests
    key, generation = session.snapshot()
    headers = dict(kwargs.pop("headers", {}))
    headers["Authorization"] = "Bearer " + key
    try:
        response = requests.post(url, headers=headers, **kwargs)
    except requests.RequestException:
        raise service_error() from None
    session.check_generation(generation)
    try:
        check_response(response)
    except CredentialError as exc:
        if exc.error_code == "MODEL_AUTH_FAILED":
            session.reset()
        raise
    return response
