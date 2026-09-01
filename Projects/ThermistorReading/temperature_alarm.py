import serial
import re
import ctypes
import winsound

PORT = "COM3"   # change this
BAUD = 9600
LIMIT = 50.0

ser = serial.Serial(PORT, BAUD, timeout=1)

alarm_active = False

print(f"Listening on {PORT}...")

while True:
    line = ser.readline().decode("utf-8", errors="ignore").strip()

    if not line:
        continue

    print(line)

    # Check for thermistor error
    if "ERR" in line and not alarm_active:
        alarm_active = True

        winsound.MessageBeep(winsound.MB_ICONHAND)

        ctypes.windll.user32.MessageBoxW(
            0,
            "One or more thermistors are reporting ERR.",
            "THERMISTOR ERROR",
            0x10
        )

        continue

    # Extract temperatures
    temps = re.findall(r"T(\d+):\s*([\d.]+)\s*C", line)

    over_limit = []

    for sensor, temp in temps:
        temp = float(temp)

        if temp >= LIMIT:
            over_limit.append((sensor, temp))

    if over_limit and not alarm_active:
        alarm_active = True

        message = "\n".join(
            f"T{sensor}: {temp:.1f} °C"
            for sensor, temp in over_limit
        )

        winsound.MessageBeep(winsound.MB_ICONHAND)

        ctypes.windll.user32.MessageBoxW(
            0,
            f"TEMPERATURE LIMIT EXCEEDED!\n\n{message}",
            "THERMISTOR WARNING",
            0x30
        )

    elif not over_limit and "ERR" not in line:
        alarm_active = False