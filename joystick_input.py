"""Background reader for the Arduino joystick, streaming 'x,y,btn' lines over serial.

Falls back gracefully (state just stays at rest) if the port can't be opened,
so the game is still playable with keyboard controls alone.
"""

import threading

import serial

PORT = "COM7"
BAUD = 9600

# Observed at rest: ~503,505,1 (button reads 1 when released, 0 when pressed
# via INPUT_PULLUP wiring). Flip these if your board's axes are mirrored.
CENTER_X = 503
CENTER_Y = 505
DEAD_ZONE = 40
AXIS_RANGE = 512  # max deflection from center, roughly 0-1023 analog range
INVERT_X = False
INVERT_Y = False


class JoystickReader:
    def __init__(self, port=PORT, baud=BAUD):
        self._lock = threading.Lock()
        self._x = 0.0  # normalized -1..1
        self._y = 0.0
        self._pressed = False
        self.connected = False

        try:
            self._ser = serial.Serial(port, baud, timeout=1)
        except Exception as e:
            print(f"[joystick] Could not open {port}: {e}")
            print("[joystick] Continuing with keyboard controls only.")
            self._ser = None
            return

        self.connected = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            try:
                line = self._ser.readline().decode(errors="ignore").strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) != 3:
                    continue
                raw_x, raw_y, raw_btn = (int(p) for p in parts)
            except Exception:
                continue

            x = (raw_x - CENTER_X) / AXIS_RANGE
            y = (raw_y - CENTER_Y) / AXIS_RANGE
            if abs(raw_x - CENTER_X) < DEAD_ZONE:
                x = 0.0
            if abs(raw_y - CENTER_Y) < DEAD_ZONE:
                y = 0.0
            x = max(-1.0, min(1.0, x))
            y = max(-1.0, min(1.0, y))
            if INVERT_X:
                x = -x
            if INVERT_Y:
                y = -y

            with self._lock:
                self._x = x
                self._y = y
                self._pressed = raw_btn == 0

    def read(self):
        """Returns (x, y, pressed) with x/y normalized to -1..1."""
        with self._lock:
            return self._x, self._y, self._pressed
