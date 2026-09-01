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
# YANG 95% SOC RELAXATION TEST SETTINGS
# ============================================================

REFERENCE_CAPACITY_AH = 13.95291

TARGET_SOC_PERCENT = 95.0

# Remove 5% of measured reference capacity
TARGET_REMOVED_CAPACITY_AH = (
    (100.0 - TARGET_SOC_PERCENT)
    / 100.0
    * REFERENCE_CAPACITY_AH
)

# 2C based on nominal 14 Ah
DISCHARGE_CURRENT_A = 28.0

# myDAQ low-voltage safety cutoff
MIN_CELL_VOLTAGE_V = 3.00

# Temperature hard stop
TEMP_LIMIT_C = 50.0

# Pre-discharge OCV baseline
PRELOAD_TIME_S = 10.0

# 2-hour relaxation
RELAXATION_TIME_S = 2 * 60 * 60

# Arduino
ARDUINO_PORT = "COM3"
ARDUINO_BAUD = 9600

# myDAQ
DAQ_CHANNEL = "myDAQ1/ai0"

# SIGLENT
SIGLENT_RESOURCE = (
    "USB0::0xF4EC::0x1621::SDL13GCD4R0583::INSTR"
)

# Logging
DISCHARGE_LOG_RATE_HZ = 5
RELAX_LOG_RATE_HZ = 5


# ============================================================
# AUTOMATIC CSV TO DOWNLOADS
# ============================================================

downloads_folder = Path.home() / "Downloads"

timestamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

CSV_FILE = downloads_folder / (
    f"yang_95SOC_2C_relaxation_{timestamp}.csv"
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
# TEMPERATURE ALARM
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

removed_capacity_Ah = 0.0

test_elapsed = 0.0
discharge_elapsed = 0.0
relax_elapsed = 0.0

mydaq_voltage = float("nan")
sdl_current = 0.0

latest_temps = []


try:

    # ========================================================
    # CONNECT SIGLENT
    # ========================================================

    print("\nConnecting to SIGLENT SDL1020X-E...")

    rm = pyvisa.ResourceManager()

    sdl = rm.open_resource(
        SIGLENT_RESOURCE,
        open_timeout=3000
    )

    sdl.timeout = 3000

    print(
        sdl.query("*IDN?").strip()
    )


    # ========================================================
    # SAFETY: FORCE LOAD OFF
    # ========================================================

    sdl.write(
        ":SOURce:INPut:STATe OFF"
    )


    # ========================================================
    # CONFIGURE 28 A CONSTANT-CURRENT DISCHARGE
    # ========================================================

    print("\nConfiguring 28 A CC discharge...")

    sdl.write(
        ":SOURce:FUNCtion CURRent"
    )

    sdl.write(
        f":SOURce:CURRent:LEVel:IMMediate "
        f"{DISCHARGE_CURRENT_A}"
    )

    # Keep load OFF
    sdl.write(
        ":SOURce:INPut:STATe OFF"
    )

    print(
        f"Current setpoint = "
        f"{DISCHARGE_CURRENT_A:.2f} A"
    )

    print(
        "LOAD IS STILL OFF"
    )


    # ========================================================
    # CONNECT ARDUINO
    # ========================================================

    print("\nConnecting Arduino...")

    arduino = serial.Serial(
        ARDUINO_PORT,
        ARDUINO_BAUD,
        timeout=0.05
    )

    time.sleep(2)

    arduino.reset_input_buffer()

    print(
        f"Arduino connected on "
        f"{ARDUINO_PORT}."
    )


    # ========================================================
    # CONNECT myDAQ
    # ========================================================

    print("\nConnecting myDAQ...")

    daq = nidaqmx.Task()

    daq.ai_channels.add_ai_voltage_chan(
        DAQ_CHANNEL,
        min_val=0.0,
        max_val=5.0
    )

    mydaq_voltage = float(
        daq.read()
    )

    print(
        f"myDAQ voltage = "
        f"{mydaq_voltage:.6f} V"
    )


    # ========================================================
    # WAIT FOR TEMPERATURES
    # ========================================================

    print("\nWaiting for thermistors...")

    wait_start = time.perf_counter()

    while (
        not latest_temps
        and
        time.perf_counter() - wait_start < 5
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
    # PRE-START SAFETY CHECKS
    # ========================================================

    if mydaq_voltage <= MIN_CELL_VOLTAGE_V:

        raise RuntimeError(
            f"Cell voltage already too low: "
            f"{mydaq_voltage:.4f} V"
        )


    if max(latest_temps) >= TEMP_LIMIT_C:

        raise RuntimeError(
            "Temperature already at/above safety limit."
        )


    # ========================================================
    # READY SCREEN
    # ========================================================

    expected_time_s = (
        TARGET_REMOVED_CAPACITY_AH
        / DISCHARGE_CURRENT_A
        * 3600.0
    )

    print("\n============================================")
    print("         YANG 95% SOC RELAXATION TEST")
    print("============================================")

    print(
        f"Reference capacity:      "
        f"{REFERENCE_CAPACITY_AH:.5f} Ah"
    )

    print(
        f"Starting SOC:            "
        f"100.0%"
    )

    print(
        f"Target SOC:              "
        f"{TARGET_SOC_PERCENT:.1f}%"
    )

    print(
        f"Capacity to remove:      "
        f"{TARGET_REMOVED_CAPACITY_AH:.7f} Ah"
    )

    print(
        f"Discharge current:       "
        f"{DISCHARGE_CURRENT_A:.2f} A"
    )

    print(
        f"Expected discharge time: "
        f"{expected_time_s:.1f} s"
    )

    print(
        f"myDAQ voltage:           "
        f"{mydaq_voltage:.4f} V"
    )

    print(
        f"Relaxation duration:     "
        f"{RELAXATION_TIME_S / 3600:.1f} h"
    )

    print(
        f"Temperature cutoff:      "
        f"{TEMP_LIMIT_C:.1f} C"
    )

    print()

    print(
        f"Ambient:                 "
        f"{ambient:.1f} C"
    )

    print(
        f"Body:                    "
        f"{body:.1f} C"
    )

    print(
        f"Negative tab:            "
        f"{negative_tab:.1f} C"
    )

    print(
        f"Positive tab:            "
        f"{positive_tab:.1f} C"
    )

    print()

    print(
        f"CSV will save to:\n"
        f"{CSV_FILE}"
    )

    print("============================================")


    input(
        "\nPress ENTER to start, "
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
            "Phase",
            "TestTime_s",
            "DischargeTime_s",
            "RelaxTime_s",
            "myDAQ_V",
            "Current_A",
            "RemovedCapacity_Ah",
            "SOC_percent",
            "Ambient_C",
            "Body_C",
            "NegativeTab_C",
            "PositiveTab_C"
        ])


        # ====================================================
        # MASTER TEST CLOCK
        # ====================================================

        test_start = time.perf_counter()


        # ====================================================
        # 10 SECOND PRE-DISCHARGE BASELINE
        # ====================================================

        print(
            f"\nRecording "
            f"{PRELOAD_TIME_S:.1f} s "
            f"pre-discharge baseline..."
        )

        while True:

            loop_start = time.perf_counter()

            test_elapsed = (
                time.perf_counter()
                - test_start
            )

            if (
                test_elapsed
                >= PRELOAD_TIME_S
            ):
                break


            # ================================================
            # myDAQ VOLTAGE
            # ================================================

            mydaq_voltage = float(
                daq.read()
            )


            # ================================================
            # LOAD OFF -> FORCE CURRENT = 0
            # ================================================

            sdl_current = 0.0
            removed_capacity_Ah = 0.0


            # ================================================
            # TEMPERATURES
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
            # TEMPERATURE SAFETY
            # ================================================

            max_temp = max(
                latest_temps
            )

            if max_temp >= TEMP_LIMIT_C:

                sdl.write(
                    ":SOURce:INPut:STATe OFF"
                )

                temperature_alarm(
                    max_temp
                )

                raise RuntimeError(
                    f"Temperature reached "
                    f"{max_temp:.1f} C "
                    f"during baseline."
                )


            # ================================================
            # SAVE BASELINE
            # ================================================

            writer.writerow([
                "BASELINE",
                f"{test_elapsed:.3f}",
                "0.000",
                "0.000",
                f"{mydaq_voltage:.6f}",
                "0.000000",
                "0.000000",
                "100.0000",
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
                f"BASELINE | "
                f"t={test_elapsed:5.1f}s | "
                f"DAQ={mydaq_voltage:.4f}V | "
                f"I=0.00A | "
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
                1.0 / DISCHARGE_LOG_RATE_HZ
                - processing_time
            )

            if sleep_time > 0:

                time.sleep(
                    sleep_time
                )


        # ====================================================
        # START 28 A DISCHARGE
        # ====================================================

        print(
            "\n\nTurning SIGLENT load ON..."
        )

        sdl.write(
            ":SOURce:INPut:STATe ON"
        )

        discharge_start = time.perf_counter()

        previous_discharge_time = 0.0

        print(
            "2C DISCHARGE STARTED\n"
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
            # SIGLENT MEASURED CURRENT
            # ================================================

            sdl_current = float(
                sdl.query(
                    "MEASure:CURRent:DC?"
                )
            )


            # ================================================
            # myDAQ CELL VOLTAGE
            # ================================================

            mydaq_voltage = float(
                daq.read()
            )


            # ================================================
            # TEMPERATURES
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
            # COULOMB COUNTING
            # ================================================

            dt = (
                discharge_elapsed
                - previous_discharge_time
            )

            removed_capacity_Ah += (
                sdl_current
                * dt
                / 3600.0
            )

            previous_discharge_time = (
                discharge_elapsed
            )


            soc_percent = (
                100.0
                *
                (
                    1.0
                    -
                    removed_capacity_Ah
                    / REFERENCE_CAPACITY_AH
                )
            )


            # ================================================
            # SAVE DISCHARGE DATA
            # ================================================

            writer.writerow([
                "DISCHARGE",
                f"{test_elapsed:.3f}",
                f"{discharge_elapsed:.3f}",
                "0.000",
                f"{mydaq_voltage:.6f}",
                f"{sdl_current:.6f}",
                f"{removed_capacity_Ah:.7f}",
                f"{soc_percent:.4f}",
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
                f"2C DISCHARGE | "
                f"t={discharge_elapsed:6.1f}s | "
                f"DAQ={mydaq_voltage:.4f}V | "
                f"I={sdl_current:.2f}A | "
                f"Removed={removed_capacity_Ah:.5f}Ah | "
                f"SOC={soc_percent:.2f}% | "
                f"Body={body:.1f}C | "
                f"-Tab={negative_tab:.1f}C | "
                f"+Tab={positive_tab:.1f}C",
                end="",
                flush=True
            )


            # ================================================
            # TEMPERATURE HARD STOP
            # ================================================

            max_temp = max(
                latest_temps
            )

            if max_temp >= TEMP_LIMIT_C:

                # LOAD OFF FIRST
                sdl.write(
                    ":SOURce:INPut:STATe OFF"
                )

                temperature_alarm(
                    max_temp
                )

                raise RuntimeError(
                    f"Temperature reached "
                    f"{max_temp:.1f} C"
                )


            # ================================================
            # LOW-VOLTAGE HARD STOP
            # ================================================

            if (
                mydaq_voltage
                <= MIN_CELL_VOLTAGE_V
            ):

                # LOAD OFF FIRST
                sdl.write(
                    ":SOURce:INPut:STATe OFF"
                )

                raise RuntimeError(
                    f"Low-voltage cutoff: "
                    f"{mydaq_voltage:.4f} V"
                )


            # ================================================
            # 95% SOC TARGET REACHED
            # ================================================

            if (
                removed_capacity_Ah
                >= TARGET_REMOVED_CAPACITY_AH
            ):

                # LOAD OFF IMMEDIATELY
                sdl.write(
                    ":SOURce:INPut:STATe OFF"
                )

                stop_reason = (
                    "95% SOC target reached"
                )

                print(
                    "\n\n95% SOC REACHED"
                )

                print(
                    f"Removed capacity = "
                    f"{removed_capacity_Ah:.7f} Ah"
                )

                print(
                    f"Calculated SOC = "
                    f"{soc_percent:.3f}%"
                )

                print(
                    f"Discharge time = "
                    f"{discharge_elapsed:.1f} s"
                )

                print(
                    "SIGLENT LOAD OFF"
                )

                break


            # ================================================
            # LOG RATE
            # ================================================

            processing_time = (
                time.perf_counter()
                - loop_start
            )

            sleep_time = (
                1.0 / DISCHARGE_LOG_RATE_HZ
                - processing_time
            )

            if sleep_time > 0:

                time.sleep(
                    sleep_time
                )


        # ====================================================
        # RELAXATION STARTS IMMEDIATELY AFTER LOAD OFF
        # ====================================================

        relax_start = time.perf_counter()

        print(
            "\nRELAXATION STARTED"
        )

        print(
            f"Recording myDAQ voltage for "
            f"{RELAXATION_TIME_S / 3600:.1f} hours.\n"
        )


        # ====================================================
        # RELAXATION LOOP
        # ====================================================

        while True:

            loop_start = time.perf_counter()

            now = time.perf_counter()

            test_elapsed = (
                now - test_start
            )

            relax_elapsed = (
                now - relax_start
            )


            if (
                relax_elapsed
                >= RELAXATION_TIME_S
            ):

                stop_reason = (
                    "2 hour relaxation complete"
                )

                break


            # ================================================
            # myDAQ VOLTAGE
            # ================================================

            mydaq_voltage = float(
                daq.read()
            )


            # ================================================
            # LOAD OFF -> CURRENT = 0
            # ================================================

            sdl_current = 0.0


            # ================================================
            # TEMPERATURES
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


            soc_percent = (
                100.0
                *
                (
                    1.0
                    -
                    removed_capacity_Ah
                    / REFERENCE_CAPACITY_AH
                )
            )


            # ================================================
            # SAVE RELAXATION DATA
            # ================================================

            writer.writerow([
                "RELAXATION",
                f"{test_elapsed:.3f}",
                f"{discharge_elapsed:.3f}",
                f"{relax_elapsed:.3f}",
                f"{mydaq_voltage:.6f}",
                "0.000000",
                f"{removed_capacity_Ah:.7f}",
                f"{soc_percent:.4f}",
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
                f"RELAX | "
                f"t={relax_elapsed:7.1f}s | "
                f"DAQ={mydaq_voltage:.5f}V | "
                f"Body={body:.1f}C | "
                f"-Tab={negative_tab:.1f}C | "
                f"+Tab={positive_tab:.1f}C",
                end="",
                flush=True
            )


            # ================================================
            # TEMPERATURE SAFETY DURING RELAXATION
            # ================================================

            max_temp = max(
                latest_temps
            )

            if max_temp >= TEMP_LIMIT_C:

                # Load should already be off, but force it off
                sdl.write(
                    ":SOURce:INPut:STATe OFF"
                )

                temperature_alarm(
                    max_temp
                )

                raise RuntimeError(
                    f"Temperature reached "
                    f"{max_temp:.1f} C"
                )


            # ================================================
            # LOG RATE
            # ================================================

            processing_time = (
                time.perf_counter()
                - loop_start
            )

            sleep_time = (
                1.0 / RELAX_LOG_RATE_HZ
                - processing_time
            )

            if sleep_time > 0:

                time.sleep(
                    sleep_time
                )


# ============================================================
# MANUAL CTRL+C STOP
# ============================================================

except KeyboardInterrupt:

    stop_reason = (
        "Manual CTRL+C stop"
    )

    print(
        "\n\nMANUAL STOP REQUESTED"
    )


# ============================================================
# ERROR
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
# ALWAYS FORCE SIGLENT LOAD OFF
# ============================================================

finally:

    if sdl is not None:

        try:

            sdl.write(
                ":SOURce:INPut:STATe OFF"
            )

            print(
                "\nSIGLENT LOAD OFF."
            )

        except Exception as error:

            print(
                "\nWARNING: Could not confirm "
                "SIGLENT load OFF!"
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

final_soc = (
    100.0
    *
    (
        1.0
        -
        removed_capacity_Ah
        / REFERENCE_CAPACITY_AH
    )
)

print("\n============================================")
print("          YANG RELAXATION TEST COMPLETE")
print("============================================")

print(
    f"Stop reason:          "
    f"{stop_reason}"
)

print(
    f"Removed capacity:     "
    f"{removed_capacity_Ah:.7f} Ah"
)

print(
    f"Calculated SOC:       "
    f"{final_soc:.3f}%"
)

print(
    f"Discharge time:       "
    f"{discharge_elapsed:.1f} s"
)

print(
    f"Relaxation time:      "
    f"{relax_elapsed:.1f} s"
)

print(
    f"Final myDAQ voltage:  "
    f"{mydaq_voltage:.6f} V"
)

print(
    f"CSV saved to:\n"
    f"{CSV_FILE}"
)

print("============================================")