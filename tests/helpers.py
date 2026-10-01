import math
import struct
import wave

RATE = 16000


def make_wav(path, segments):
    """segments : liste de (durée_s, amplitude 0..1) ; amplitude 0 = silence, sinon sinus 440 Hz."""
    frames = bytearray()
    for dur, amp in segments:
        for i in range(int(dur * RATE)):
            frames += struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * 440 * i / RATE)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return path
