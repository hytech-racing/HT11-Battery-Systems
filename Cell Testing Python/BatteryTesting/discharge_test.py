import csv
import re
import time
import ctypes
import winsound
from datetime import datetime
from pathlib import Path

import serial
import pyvisa
import nidaqmx


# ============================================================
# TEST SETTINGS
# ============================================================

DISCHARGE_CURRENT_A = 4.67

# myDAQ controls voltage cutoff
CUTOFF_VOLTAGE_V = 3.00

TEMP_LIMIT_C = 50.0

# Record cell voltage for 10 seconds before load turns on
PRELOAD_TIME_S = 10.0

ARDUINO_PORT = "COM3"
ARDUINO_BAUD = 9600

DAQ_CHANNEL = "myDAQ1/ai0"

SIGLENT_RESOURCE = (
    "USB0::0xF4EC::0x1621::SDL13GCD4R0583::INSTR"
)

LOG_RATE_HZ = 5


# ============================================================
# AUTOMATIC CSV FILE IN DOWNLOADS
# ============================================================

downloads_folder = Path.home() / "Downloads"

timestamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

CSV_FILE = downloads_folder / (
    f"discharge_test_{timestamp}.csv"
)


# ============================================================
# READ ARDUINO TEMPERATURES
# ============================================================

def read_temperatures(arduino):

    latest_line = None

    while arduino.in_waiting > 0:

        try:
            line = arduino.readline().decode(
                "utf-8",
                errors="ignore"
            ).strip()

            if line:
                latest_line = line

        except Exception:
            return None

    if latest_line is None:
        return None

    matches = re.findall(
        r":\s*(-?\d+(?:\.\d+)?)\s*C",
        latest_line
    )

    if len(matches) != 4:
        return None

    return [float(x) for x in matches]


# ============================================================
# WINDOWS TEMPERATURE ALARM
# ============================================================

def temperature_alarm(max_temp):

    try:
        winsound.Beep(1800, 600)
        winsound.Beep(1800, 600)
        winsound.Beep(1800, 600)

    except Exception:
        pass

    ctypes.windll.user32.MessageBoxW(
        0,
        (
            "BATTERY TEST STOPPED\n\n"
            f"Temperature reached {max_temp:.1f} C\n"
            f"Limit = {TEMP_LIMIT_C:.1f} C\n\n"
            "SIGLENT LOAD HAS BEEN TURNED OFF."
        ),
        "BATTERY TEMPERATURE LIMIT",
        0x10 | 0x1000
    )


# ============================================================
# INITIALIZE
# ============================================================

rm = None
sdl = None
arduino = None
daq = None

stop_reason = "Unknown"

test_elapsed = 0.0
discharge_elapsed = 0.0

capacity_Ah = 0.0

siglent_current = float("nan")
mydaq_voltage = float("nan")

latest_temps = []

load_on = False


try:

    # ========================================================
    # CONNECT SIGLENT
    # ========================================================

    print("\nConnecting to SIGLENT...")

    rm = pyvisa.ResourceManager()

    sdl = rm.open_resource(
        SIGLENT_RESOURCE,
        open_timeout=3000
    )

    sdl.timeout = 3000

    idn = sdl.query("*IDN?").strip()

    print("Connected:")
    print(idn)

    # Force load OFF
    sdl.write(
        ":SOURce:INPut:STATe OFF"
    )


    # ========================================================
    # CONNECT ARDUINO
    # ========================================================

    print("\nConnecting to Arduino...")

    arduino = serial.Serial(
        ARDUINO_PORT,
        ARDUINO_BAUD,
        timeout=0.05
    )

    time.sleep(2)

    arduino.reset_input_buffer()

    print(
        f"Arduino connected on "
        f"{ARDUINO_PORT} @ {ARDUINO_BAUD} baud."
    )


    # ========================================================
    # CONNECT myDAQ
    # ========================================================

    print("\nConnecting to myDAQ...")

    daq = nidaqmx.Task()

    daq.ai_channels.add_ai_voltage_chan(
        DAQ_CHANNEL,
        min_val=0.0,
        max_val=5.0
    )

    print(
        f"myDAQ connected on {DAQ_CHANNEL}."
    )


    # ========================================================
    # CONFIGURE SIGLENT
    # ========================================================

    print("\nConfiguring SIGLENT...")

    sdl.write(
        ":SOURce:FUNCtion CURRent"
    )

    sdl.write(
        f":SOURce:CURRent:LEVel:IMMediate "
        f"{DISCHARGE_CURRENT_A}"
    )

    sdl.write(
        ":SOURce:INPut:STATe OFF"
    )


    # ========================================================
    # INITIAL READINGS
    # ========================================================

    siglent_current = float(
        sdl.query(
            "MEASure:CURRent:DC?"
        )
    )

    mydaq_voltage = float(
        daq.read()
    )


    # ========================================================
    # WAIT FOR TEMPERATURE DATA
    # ========================================================

    print("\nWaiting for thermistor data...")

    temp_wait_start = time.perf_counter()

    while (
        not latest_temps
        and
        time.perf_counter() - temp_wait_start < 5
    ):

        temps = read_temperatures(
            arduino
        )

        if temps is not None:
            latest_temps = temps

        time.sleep(0.05)


    if len(latest_temps) != 4:

        raise RuntimeError(
            "Could not read all 4 thermistors."
        )


    ambient = latest_temps[0]
    body = latest_temps[1]
    negative_tab = latest_temps[2]
    positive_tab = latest_temps[3]


    # ========================================================
    # PRE-START CHECKS
    # ========================================================

    if mydaq_voltage <= CUTOFF_VOLTAGE_V:

        raise RuntimeError(
            f"myDAQ voltage is already "
            f"{mydaq_voltage:.4f} V, "
            f"at/below cutoff."
        )


    max_temp = max(latest_temps)

    if max_temp >= TEMP_LIMIT_C:

        raise RuntimeError(
            f"Temperature already at "
            f"{max_temp:.1f} C."
        )


    # ========================================================
    # READY SCREEN
    # ========================================================

    print("\n============================================")
    print("               TEST READY")
    print("============================================")

    print(
        f"myDAQ voltage:        "
        f"{mydaq_voltage:.4f} V"
    )

    print(
        f"Ambient:              "
        f"{ambient:.1f} C"
    )

    print(
        f"Cell body:            "
        f"{body:.1f} C"
    )

    print(
        f"Negative tab:         "
        f"{negative_tab:.1f} C"
    )

    print(
        f"Positive tab:         "
        f"{positive_tab:.1f} C"
    )

    print()

    print(
        f"Pre-load recording:   "
        f"{PRELOAD_TIME_S:.1f} s"
    )

    print(
        f"Discharge current:    "
        f"{DISCHARGE_CURRENT_A:.2f} A"
    )

    print(
        f"myDAQ cutoff:         "
        f"{CUTOFF_VOLTAGE_V:.2f} V"
    )

    print(
        f"Temperature cutoff:   "
        f"{TEMP_LIMIT_C:.1f} C"
    )

    print()

    print(
        f"CSV will save to:\n"
        f"{CSV_FILE}"
    )

    print("============================================")


    input(
        "\nPress ENTER to start test, "
        "or CTRL+C to abort: "
    )


    # ========================================================
    # OPEN CSV
    # ========================================================

    with open(
        CSV_FILE,
        "w",
        newline=""
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "TestTime_s",
            "DischargeTime_s",
            "myDAQ_V",
            "Current_A",
            "Capacity_Ah",
            "Ambient_C",
            "Body_C",
            "NegativeTab_C",
            "PositiveTab_C"
        ])


        # ====================================================
        # START MASTER TEST CLOCK
        # ====================================================

        test_start = time.perf_counter()


        # ====================================================
        # 10 SECOND PRE-LOAD RECORDING
        # ====================================================

        print(
            f"\nRecording "
            f"{PRELOAD_TIME_S:.1f} s "
            f"pre-load baseline..."
        )

        while True:

            loop_start = time.perf_counter()

            test_elapsed = (
                time.perf_counter()
                - test_start
            )

            if test_elapsed >= PRELOAD_TIME_S:
                break


            # myDAQ voltage
            mydaq_voltage = float(
                daq.read()
            )


            # Arduino temperatures
            new_temps = read_temperatures(
                arduino
            )

            if new_temps is not None:
                latest_temps = new_temps


            ambient = latest_temps[0]
            body = latest_temps[1]
            negative_tab = latest_temps[2]
            positive_tab = latest_temps[3]


            # Load is OFF during preload
            siglent_current = 0.0


            # Thermal safety
            max_temp = max(
                ambient,
                body,
                negative_tab,
                positive_tab
            )

            if max_temp >= TEMP_LIMIT_C:

                stop_reason = (
                    f"Temperature reached "
                    f"{max_temp:.1f} C "
                    f"during preload"
                )

                temperature_alarm(
                    max_temp
                )

                raise RuntimeError(
                    stop_reason
                )


            # Save preload data
            writer.writerow([
                f"{test_elapsed:.3f}",
                "0.000",
                f"{mydaq_voltage:.6f}",
                f"{siglent_current:.6f}",
                f"{capacity_Ah:.6f}",
                f"{ambient:.2f}",
                f"{body:.2f}",
                f"{negative_tab:.2f}",
                f"{positive_tab:.2f}"
            ])

            file.flush()


            # Live display
            print(
                "\r"
                f"PRELOAD | "
                f"t={test_elapsed:5.1f}s | "
                f"DAQ={mydaq_voltage:.4f}V | "
                f"Amb={ambient:.1f}C | "
                f"Body={body:.1f}C | "
                f"-Tab={negative_tab:.1f}C | "
                f"+Tab={positive_tab:.1f}C",
                end="",
                flush=True
            )


            processing_time = (
                time.perf_counter()
                - loop_start
            )

            sleep_time = (
                1.0 / LOG_RATE_HZ
                - processing_time
            )

            if sleep_time > 0:
                time.sleep(
                    sleep_time
                )


        # ====================================================
        # TURN LOAD ON
        # ====================================================

        print(
            "\n\nPre-load recording complete."
        )

        print(
            "Turning SIGLENT load ON..."
        )

        sdl.write(
            ":SOURce:INPut:STATe ON"
        )

        load_on = True

        # Discharge clock starts here
        discharge_start = time.perf_counter()

        previous_discharge_time = 0.0

        print(
            "DISCHARGE STARTED\n"
        )


        # ====================================================
        # DISCHARGE LOOP
        # ====================================================

        while True:

            loop_start = time.perf_counter()

            now = time.perf_counter()

            test_elapsed = (
                now - test_start
            )

            discharge_elapsed = (
                now - discharge_start
            )


            # ================================================
            # SIGLENT CURRENT
            # ================================================

            siglent_current = float(
                sdl.query(
                    "MEASure:CURRent:DC?"
                )
            )


            # ================================================
            # myDAQ VOLTAGE
            # ================================================

            mydaq_voltage = float(
                daq.read()
            )


            # ================================================
            # ARDUINO TEMPERATURES
            # ================================================

            new_temps = read_temperatures(
                arduino
            )

            if new_temps is not None:
                latest_temps = new_temps


            ambient = latest_temps[0]
            body = latest_temps[1]
            negative_tab = latest_temps[2]
            positive_tab = latest_temps[3]


            # ================================================
            # CAPACITY INTEGRATION
            # ================================================

            dt = (
                discharge_elapsed
                - previous_discharge_time
            )

            capacity_Ah += (
                siglent_current
                * dt
                / 3600.0
            )

            previous_discharge_time = (
                discharge_elapsed
            )


            # ================================================
            # SAVE DATA
            # ================================================

            writer.writerow([
                f"{test_elapsed:.3f}",
                f"{discharge_elapsed:.3f}",
                f"{mydaq_voltage:.6f}",
                f"{siglent_current:.6f}",
                f"{capacity_Ah:.6f}",
                f"{ambient:.2f}",
                f"{body:.2f}",
                f"{negative_tab:.2f}",
                f"{positive_tab:.2f}"
            ])

            file.flush()


            # ================================================
            # LIVE DISPLAY
            # ================================================

            print(
                "\r"
                f"DISCHARGE | "
                f"t={discharge_elapsed:7.1f}s | "
                f"DAQ={mydaq_voltage:.4f}V | "
                f"I={siglent_current:.3f}A | "
                f"Q={capacity_Ah:.4f}Ah | "
                f"Amb={ambient:.1f}C | "
                f"Body={body:.1f}C | "
                f"-Tab={negative_tab:.1f}C | "
                f"+Tab={positive_tab:.1f}C",
                end="",
                flush=True
            )


            # ================================================
            # myDAQ VOLTAGE CUTOFF
            # ================================================

            if (
                mydaq_voltage
                <= CUTOFF_VOLTAGE_V
            ):

                stop_reason = (
                    f"myDAQ reached "
                    f"{mydaq_voltage:.4f} V"
                )

                sdl.write(
                    ":SOURce:INPut:STATe OFF"
                )

                load_on = False

                print(
                    "\n\nVOLTAGE CUTOFF REACHED"
                )

                print(
                    f"myDAQ = "
                    f"{mydaq_voltage:.4f} V"
                )

                print(
                    f"Capacity = "
                    f"{capacity_Ah:.4f} Ah"
                )

                print(
                    "SIGLENT LOAD OFF"
                )

                break


            # ================================================
            # TEMPERATURE CUTOFF
            # ================================================

            max_temp = max(
                ambient,
                body,
                negative_tab,
                positive_tab
            )

            if max_temp >= TEMP_LIMIT_C:

                stop_reason = (
                    f"Temperature reached "
                    f"{max_temp:.1f} C"
                )

                sdl.write(
                    ":SOURce:INPut:STATe OFF"
                )

                load_on = False

                print(
                    "\n\nTEMPERATURE CUTOFF REACHED"
                )

                print(
                    f"Maximum temperature = "
                    f"{max_temp:.1f} C"
                )

                print(
                    "SIGLENT LOAD OFF"
                )

                temperature_alarm(
                    max_temp
                )

                break


            # ================================================
            # APPROXIMATE LOGGING RATE
            # ================================================

            processing_time = (
                time.perf_counter()
                - loop_start
            )

            sleep_time = (
                1.0 / LOG_RATE_HZ
                - processing_time
            )

            if sleep_time > 0:

                time.sleep(
                    sleep_time
                )


# ============================================================
# MANUAL STOP
# ============================================================

except KeyboardInterrupt:

    stop_reason = (
        "Manual CTRL+C stop"
    )

    print(
        "\n\nMANUAL STOP REQUESTED"
    )


# ============================================================
# PROGRAM ERROR
# ============================================================

except Exception as error:

    stop_reason = (
        f"Program error: {error}"
    )

    print(
        "\n\nTEST ERROR:"
    )

    print(error)


# ============================================================
# ALWAYS FORCE LOAD OFF
# ============================================================

finally:

    if sdl is not None:

        try:

            sdl.write(
                ":SOURce:INPut:STATe OFF"
            )

            load_on = False

            print(
                "\nSIGLENT LOAD OFF."
            )

        except Exception as error:

            print(
                "\nWARNING: Could not confirm "
                "SIGLENT LOAD OFF!"
            )

            print(error)


    if daq is not None:

        try:
            daq.close()
        except Exception:
            pass


    if arduino is not None:

        try:
            arduino.close()
        except Exception:
            pass


    if sdl is not None:

        try:
            sdl.close()
        except Exception:
            pass


    if rm is not None:

        try:
            rm.close()
        except Exception:
            pass


# ============================================================
# FINAL RESULTS
# ============================================================

print("\n============================================")
print("               TEST COMPLETE")
print("============================================")

print(
    f"Stop reason:          "
    f"{stop_reason}"
)

print(
    f"Total test time:      "
    f"{test_elapsed:.1f} s"
)

print(
    f"Discharge time:       "
    f"{discharge_elapsed:.1f} s"
)

print(
    f"Discharged capacity:  "
    f"{capacity_Ah:.4f} Ah"
)

print(
    f"Final myDAQ V:        "
    f"{mydaq_voltage:.4f} V"
)

print(
    f"CSV saved to:\n"
    f"{CSV_FILE}"
)

print("============================================")