"""Client whisper-server (whisper.cpp) : POST multipart sur /inference."""
from __future__ import annotations

import uuid
from pathlib import Path

from .services import ServiceError, post


def _multipart(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n".encode() + file_path.read_bytes() + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(wav: Path | str, url: str, language: str, prompt: str, timeout_s: float) -> str:
    fields = {"response_format": "json", "temperature": "0.0", "language": language}
    if prompt:
        fields["prompt"] = prompt
    body, ctype = _multipart(fields, "file", Path(wav))
    data = post("whisper", url.rstrip("/") + "/inference", body, ctype, timeout_s)
    if "text" not in data:
        raise ServiceError("whisper", f"réponse inattendue : {str(data)[:200]}")
    return data["text"]
