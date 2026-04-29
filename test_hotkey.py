from pynput import keyboard

def on_press(key):
    print(f"Key: {repr(key)}")

print("Press Ctrl+S now (Ctrl+C to quit)...")
with keyboard.Listener(on_press=on_press) as l:
    l.join()
