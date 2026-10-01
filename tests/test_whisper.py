import pytest

from dictate.services import ServiceError
from dictate.whisper import transcribe


def test_transcribe_sends_multipart_fields(fake_server, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....WAVEfake")
    fake_server.response = {"text": " Bonjour le monde.\n"}
    text = transcribe(wav, url=fake_server.url, language="fr", prompt="Claude Code, Codex.", timeout_s=5)
    assert text == " Bonjour le monde.\n"
    path, headers, body = fake_server.requests[0]
    assert path == "/inference"
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="a.wav"' in body
    assert b"RIFF....WAVEfake" in body
    assert b'name="language"\r\n\r\nfr\r\n' in body
    assert 'name="prompt"\r\n\r\nClaude Code, Codex.\r\n'.encode() in body
    assert b'name="temperature"\r\n\r\n0' in body
    assert b'name="response_format"\r\n\r\njson\r\n' in body


def test_transcribe_omits_empty_prompt(fake_server, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    fake_server.response = {"text": "ok"}
    transcribe(wav, url=fake_server.url, language="auto", prompt="", timeout_s=5)
    assert b'name="prompt"' not in fake_server.requests[0][2]


def test_transcribe_service_down(dead_url, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    with pytest.raises(ServiceError) as e:
        transcribe(wav, url=dead_url, language="fr", prompt="", timeout_s=2)
    assert e.value.service == "whisper"
    assert "injoignable" in str(e.value)


def test_transcribe_http_error(fake_server, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    fake_server.status = 500
    fake_server.response = {"error": "boom"}
    with pytest.raises(ServiceError, match="500"):
        transcribe(wav, url=fake_server.url, language="fr", prompt="", timeout_s=2)


def test_transcribe_server_error_payload(fake_server, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    fake_server.response = {"error": "failed to read audio"}
    with pytest.raises(ServiceError, match="failed to read audio"):
        transcribe(wav, url=fake_server.url, language="fr", prompt="", timeout_s=2)


def test_transcribe_timeout(fake_server, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    fake_server.delay_s = 1.0
    fake_server.response = {"text": "trop tard"}
    with pytest.raises(ServiceError, match="délai"):
        transcribe(wav, url=fake_server.url, language="fr", prompt="", timeout_s=0.2)
