import sounddevice as sd
import numpy as np
import wave
import tempfile
import os

print("Recording 3 seconds... speak now!")
audio = sd.rec(int(3 * 16000), samplerate=16000, channels=1, dtype='float32')
sd.wait()

# Check volume
rms = np.sqrt(np.mean(audio**2))
max_val = np.max(np.abs(audio))
print(f"RMS volume: {rms:.4f}")
print(f"Max value:  {max_val:.4f}")

if max_val < 0.01:
    print("WARNING: Audio is nearly silent — mic may not be capturing input")
else:
    print("Audio level looks OK")

# Save and play back
path = os.path.expanduser("~/Desktop/dictation/test_recording.wav")
with wave.open(path, "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes((audio * 32767).astype(np.int16).tobytes())

print(f"\nSaved to {path}")
print("Open it in QuickTime to hear if your voice was captured.")
