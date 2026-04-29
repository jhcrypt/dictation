import sounddevice as sd
print(sd.query_devices())
print("\nDefault input device:")
print(sd.query_devices(kind='input'))
