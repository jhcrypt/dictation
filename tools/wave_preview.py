"""
Siri-style wave animation preview.
Run:  python tools/wave_preview.py
Close the window when done. Nothing in the app is changed.
"""
import tkinter as tk
import math, time

W, H = 420, 52
BG   = "#1c1c1c"
PILL = "#242424"

# Siri-style wave layers: (amplitude_factor, freq_mult, phase_offset, color, linewidth)
SIRI_WAVES = [
    (0.82, 1.00, 0.00, "#ffffff", 2),   # white  — dominant
    (0.62, 1.30, 1.10, "#0a84ff", 2),   # blue
    (0.52, 0.75, 2.20, "#bf5af2", 2),   # purple
    (0.42, 1.55, 3.30, "#5ac8fa", 1),   # cyan
    (0.34, 0.90, 4.40, "#30d158", 1),   # green
]

X_START, X_END = 8, 72   # same footprint as the current bars
POINTS  = 48             # curve resolution
SPEED   = 0.10           # phase advance per frame
FPS     = 30

root = tk.Tk()
root.title("Wave preview — close when done")
root.configure(bg=BG)
root.resizable(False, False)
root.geometry(f"{W}x{H+60}")   # extra height for the two comparison rows

canvas = tk.Canvas(root, width=W, height=H+60, bg=BG,
                   highlightthickness=0)
canvas.pack()

# ── Draw pill background ──────────────────────────────────────────────────────
r = H // 2
pts = [r,0, W-r,0, W,r, W,H-r, W-r,H, r,H, 0,H-r, 0,r]
canvas.create_polygon(pts, smooth=True, fill=PILL, outline="")

# Divider + text (matches real HUD)
canvas.create_line(46, 14, 46, H-14, fill="#303030", width=1)
canvas.create_text(80, H//2, text="Jarvis recording... keep speaking.",
                   font=("Helvetica Neue", 13), fill="#ffffff", anchor="w", width=260)
canvas.create_text(W-14, H//2, text="✕",
                   font=("Helvetica", 10), fill="#4a4a4a", anchor="center")

# ── Create wave line items ────────────────────────────────────────────────────
wave_items = []
for _, _, _, color, lw in SIRI_WAVES:
    item = canvas.create_line(0, 0, 0, 0, fill=color, width=lw, smooth=True)
    wave_items.append(item)

# ── Labels ────────────────────────────────────────────────────────────────────
canvas.create_text(W//2, H+14, text="▲  NEW  (Siri-style waves)",
                   font=("Helvetica Neue", 10), fill="#30d158")
canvas.create_text(W//2, H+30, text="▼  CURRENT  (red bars  —  static preview)",
                   font=("Helvetica Neue", 10), fill="#ff3b30")

# ── Current-style bars (static, for comparison) ───────────────────────────────
bar_y = H + 48
for i in range(14):
    x = 8 + i * 5
    dist = abs(i - 7) / 7
    brightness = int(255 * (1 - dist * 0.65))
    h_bar = max(2, int(10 * (math.sin(i * 0.55) * 0.5 + 0.5) * (1 - dist * 0.5)))
    canvas.create_rectangle(x, bar_y - h_bar, x+3, bar_y + h_bar,
                             fill=f"#{brightness:02x}{int(brightness*0.18):02x}"
                                  f"{int(brightness*0.12):02x}", outline="")

# ── Animation loop ────────────────────────────────────────────────────────────
phase = [0.0]
start = time.time()

def animate():
    phase[0] += SPEED
    # Simulate breathing audio level (0.3 – 1.0) so you can see it pulse
    t = time.time() - start
    simulated_rms = 0.55 + 0.45 * math.sin(t * 1.8)

    cy   = H // 2
    mamp = (cy - 6) * simulated_rms

    for item, (amp_f, freq, poff, color, lw) in zip(wave_items, SIRI_WAVES):
        pts = []
        for j in range(POINTS + 1):
            x = X_START + (X_END - X_START) * j / POINTS
            y = cy + math.sin(phase[0] * freq + poff + j * 0.28) * mamp * amp_f
            pts.extend([x, y])
        canvas.coords(item, pts)

    root.after(1000 // FPS, animate)

animate()
root.mainloop()
