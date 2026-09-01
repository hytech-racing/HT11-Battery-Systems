import serial
import time

ARDUINO_PORT = "COM3"   # change to your actual Arduino COM port
ARDUINO_BAUD = 9600

arduino = serial.Serial(
    ARDUINO_PORT,
    ARDUINO_BAUD,
    timeout=1
)

time.sleep(2)

print("Reading Arduino temperatures...")
print("Press CTRL+C to stop.\n")

try:
    while True:
        line = arduino.readline().decode(
            "utf-8",
            errors="ignore"
        ).strip()

        if line:
            print(line)

except KeyboardInterrupt:
    print("\nStopped.")

finally:
    arduino.close()