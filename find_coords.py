"""Find pixel coordinates on screen, for use with the click_at/type_text
tools (or JARVIS_MODEL config, or anything else that wants x/y).

Run it, then hover your mouse over whatever you want the coordinates for
during the countdown -- position is captured and printed the moment it
hits zero.

    venv\\Scripts\\python.exe find_coords.py
"""

import time

import pyautogui

print("Move your mouse to the spot you want coordinates for...")
for n in (3, 2, 1):
    print(n, flush=True)
    time.sleep(1)

x, y = pyautogui.position()
print(f"\nCoordinates: x={x}, y={y}")
