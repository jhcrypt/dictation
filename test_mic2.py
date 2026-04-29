import sounddevice as sd
import numpy as np

print("Testing device 2 at 48000Hz for 3 seconds... speak now!")
audio = sd.rec(int(3 * 48000), samplerate=48000, channels=1, dtype='float32', device=2)
sd.wait()

rms = np.sqrt(np.mean(audio**2))
max_val = np.max(np.abs(audio))
print(f"RMS: {rms:.6f}  Max: {max_val:.6f}")

# Try all input devices
print("\n--- Testing all input devices ---")
import sounddevice as sd
devices = sd.query_devices()
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        try:
            a = sd.rec(int(48000), samplerate=48000, channels=1, dtype='float32', device=i)
            sd.wait()
            r = np.sqrt(np.mean(a**2))
            print(f"Device {i} ({d['name']}): RMS={r:.6f}")
        except Exception as e:
            print(f"Device {i} ({d['name']}): ERROR - {e}")
