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

CELL_CAPACITY_AH = 14.0

# C/3
CHARGE_CURRENT_A = 4.67

# Constant-voltage target
TARGET_VOLTAGE_V = 4.35

# 0.05C = 0.70 A for a 14 Ah cell
TERMINATION_CURRENT_A = 0.70

# Require termination condition continuously for this long
TERMINATION_HOLD_TIME_S = 3.0

# How close to target voltage we must be before
# low current is allowed to terminate the test
CV_VOLTAGE_TOLERANCE_V = 0.005

TEMP_LIMIT_C = 50.0

PRECHARGE_TIME_S = 10.0

ARDUINO_PORT = "COM3"
ARDUINO_BAUD = 9600

DAQ_CHANNEL = "myDAQ1/ai0"

KEYSIGHT_RESOURCE = (
    "USB0::0x2A8D::0x2F02::MY59001492::INSTR"
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
    f"charge_test_{timestamp}.csv"
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
            "BATTERY CHARGE TEST STOPPED\n\n"
            f"Temperature reached {max_temp:.1f} C\n"
            f"Limit = {TEMP_LIMIT_C:.1f} C\n\n"
            "KEYSIGHT OUTPUT HAS BEEN TURNED OFF."
        ),
        "BATTERY TEMPERATURE LIMIT",
        0x10 | 0x1000
    )


# ============================================================
# INITIALIZE
# ============================================================

rm = None
supply = None
arduino = None
daq = None

stop_reason = "Unknown"

test_elapsed = 0.0
charge_elapsed = 0.0

charge_capacity_Ah = 0.0

sense_voltage = float("nan")
mydaq_voltage = float("nan")
measured_current = 0.0

latest_temps = []

termination_start = None


try:

    # ========================================================
    # CONNECT KEYSIGHT
    # ========================================================

    print("\nConnecting to Keysight E36231A...")

    rm = pyvisa.ResourceManager()

    supply = rm.open_resource(
        KEYSIGHT_RESOURCE,
        open_timeout=3000
    )

    supply.timeout = 3000

    idn = supply.query("*IDN?").strip()

    print("Connected:")
    print(idn)


    # ========================================================
    # SAFETY: FORCE OUTPUT OFF
    # ========================================================

    supply.write("OUTP OFF")


    # ========================================================
    # ENABLE 4-WIRE REMOTE SENSE
    # ========================================================

    supply.write(
        "VOLT:SENS:SOUR EXT"
    )

    sense_mode = supply.query(
        "VOLT:SENS:SOUR?"
    ).strip()

    print(
        f"Sense mode: {sense_mode}"
    )


    # ========================================================
    # CONFIGURE CC-CV CHARGE
    # ========================================================

    print("\nConfiguring Keysight...")

    # CV voltage target
    supply.write(
        f"VOLT {TARGET_VOLTAGE_V}"
    )

    # CC current limit
    supply.write(
        f"CURR {CHARGE_CURRENT_A}"
    )

    # Keep output OFF
    supply.write(
        "OUTP OFF"
    )


    # ========================================================
    # VERIFY PROGRAMMED SETTINGS
    # ========================================================

    programmed_voltage = float(
        supply.query("VOLT?")
    )

    programmed_current = float(
        supply.query("CURR?")
    )

    print(
        f"Programmed voltage: "
        f"{programmed_voltage:.4f} V"
    )

    print(
        f"Programmed current: "
        f"{programmed_current:.3f} A"
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
    # INITIAL VOLTAGE READINGS
    # ========================================================

    sense_voltage = float(
        supply.query(
            "MEAS:VOLT?"
        )
    )

    mydaq_voltage = float(
        daq.read()
    )


    # ========================================================
    # WAIT FOR THERMISTORS
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
    # PRE-START SAFETY CHECKS
    # ========================================================

    if sense_voltage >= TARGET_VOLTAGE_V:

        raise RuntimeError(
            f"Keysight sense voltage is already "
            f"{sense_voltage:.4f} V, "
            f"at/above the {TARGET_VOLTAGE_V:.3f} V target."
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
    print("            CC-CV CHARGE TEST READY")
    print("============================================")

    print(
        f"Keysight sense V:     "
        f"{sense_voltage:.4f} V"
    )

    print(
        f"myDAQ voltage:        "
        f"{mydaq_voltage:.4f} V"
    )

    print(
        f"Sense mode:           "
        f"{sense_mode}"
    )

    print()

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
        f"CC current:           "
        f"{CHARGE_CURRENT_A:.2f} A"
    )

    print(
        f"CV voltage:           "
        f"{TARGET_VOLTAGE_V:.3f} V"
    )

    print(
        f"Termination current:  "
        f"{TERMINATION_CURRENT_A:.2f} A"
    )

    print(
        f"Termination hold:     "
        f"{TERMINATION_HOLD_TIME_S:.1f} s"
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
        "\nCheck the readings above.\n"
        "Press ENTER to START charge, "
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
            "ChargeTime_s",
            "SenseVoltage_V",
            "myDAQ_V",
            "Current_A",
            "ChargeCapacity_Ah",
            "Ambient_C",
            "Body_C",
            "NegativeTab_C",
            "PositiveTab_C"
        ])


        # ====================================================
        # MASTER CLOCK
        # ====================================================

        test_start = time.perf_counter()


        # ====================================================
        # 10 SECOND PRE-CHARGE BASELINE
        # ====================================================

        print(
            f"\nRecording "
            f"{PRECHARGE_TIME_S:.1f} s "
            f"pre-charge baseline..."
        )

        while True:

            loop_start = time.perf_counter()

            test_elapsed = (
                time.perf_counter()
                - test_start
            )

            if (
                test_elapsed
                >= PRECHARGE_TIME_S
            ):
                break


            # Keysight sense voltage
            sense_voltage = float(
                supply.query(
                    "MEAS:VOLT?"
                )
            )


            # myDAQ voltage
            mydaq_voltage = float(
                daq.read()
            )


            # Output is OFF:
            # force logged current and capacity to zero
            measured_current = 0.0
            charge_capacity_Ah = 0.0


            # Temperatures
            new_temps = read_temperatures(
                arduino
            )

            if new_temps is not None:
                latest_temps = new_temps


            ambient = latest_temps[0]
            body = latest_temps[1]
            negative_tab = latest_temps[2]
            positive_tab = latest_temps[3]


            # Thermal safety
            max_temp = max(
                latest_temps
            )

            if max_temp >= TEMP_LIMIT_C:

                stop_reason = (
                    f"Temperature reached "
                    f"{max_temp:.1f} C "
                    f"during baseline"
                )

                supply.write(
                    "OUTP OFF"
                )

                temperature_alarm(
                    max_temp
                )

                raise RuntimeError(
                    stop_reason
                )


            # Save baseline
            writer.writerow([
                f"{test_elapsed:.3f}",
                "0.000",
                f"{sense_voltage:.6f}",
                f"{mydaq_voltage:.6f}",
                "0.000000",
                "0.000000",
                f"{ambient:.2f}",
                f"{body:.2f}",
                f"{negative_tab:.2f}",
                f"{positive_tab:.2f}"
            ])

            file.flush()


            # Live display
            print(
                "\r"
                f"BASELINE | "
                f"t={test_elapsed:5.1f}s | "
                f"Sense={sense_voltage:.4f}V | "
                f"DAQ={mydaq_voltage:.4f}V | "
                f"I=0.000A | "
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
        # TURN CHARGER ON
        # ====================================================

        print(
            "\n\nPre-charge baseline complete."
        )

        print(
            "Turning Keysight output ON..."
        )

        supply.write(
            "OUTP ON"
        )

        charge_start = time.perf_counter()

        previous_charge_time = 0.0

        termination_start = None


        print(
            "CHARGING STARTED"
        )

        print(
            f"CC at up to {CHARGE_CURRENT_A:.2f} A "
            f"until {TARGET_VOLTAGE_V:.3f} V."
        )

        print(
            f"Then CV at {TARGET_VOLTAGE_V:.3f} V "
            f"until I <= {TERMINATION_CURRENT_A:.2f} A.\n"
        )


        # ====================================================
        # CHARGE LOOP
        # ====================================================

        while True:

            loop_start = time.perf_counter()

            now = time.perf_counter()

            test_elapsed = (
                now - test_start
            )

            charge_elapsed = (
                now - charge_start
            )


            # ================================================
            # KEYSIGHT REMOTE-SENSE VOLTAGE
            # ================================================

            sense_voltage = float(
                supply.query(
                    "MEAS:VOLT?"
                )
            )


            # ================================================
            # KEYSIGHT OUTPUT CURRENT
            # ================================================

            measured_current = float(
                supply.query(
                    "MEAS:CURR?"
                )
            )


            # ================================================
            # myDAQ VOLTAGE
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
            # INTEGRATE CHARGE CAPACITY
            # ================================================

            dt = (
                charge_elapsed
                - previous_charge_time
            )

            charge_capacity_Ah += (
                measured_current
                * dt
                / 3600.0
            )

            previous_charge_time = (
                charge_elapsed
            )


            # ================================================
            # SAVE DATA
            # ================================================

            writer.writerow([
                f"{test_elapsed:.3f}",
                f"{charge_elapsed:.3f}",
                f"{sense_voltage:.6f}",
                f"{mydaq_voltage:.6f}",
                f"{measured_current:.6f}",
                f"{charge_capacity_Ah:.6f}",
                f"{ambient:.2f}",
                f"{body:.2f}",
                f"{negative_tab:.2f}",
                f"{positive_tab:.2f}"
            ])

            file.flush()


            # ================================================
            # DETERMINE CHARGE PHASE FOR DISPLAY
            # ================================================

            if (
                sense_voltage
                >= TARGET_VOLTAGE_V
                - CV_VOLTAGE_TOLERANCE_V
            ):

                charge_phase = "CV"

            else:

                charge_phase = "CC"


            # ================================================
            # LIVE TERMINAL DISPLAY
            # ================================================

            print(
                "\r"
                f"{charge_phase} | "
                f"t={charge_elapsed:7.1f}s | "
                f"Sense={sense_voltage:.4f}V | "
                f"DAQ={mydaq_voltage:.4f}V | "
                f"I={measured_current:.3f}A | "
                f"Q={charge_capacity_Ah:.4f}Ah | "
                f"Amb={ambient:.1f}C | "
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

                stop_reason = (
                    f"Temperature reached "
                    f"{max_temp:.1f} C"
                )

                # OUTPUT OFF FIRST
                supply.write(
                    "OUTP OFF"
                )

                print(
                    "\n\nTEMPERATURE LIMIT REACHED"
                )

                print(
                    f"Maximum temperature = "
                    f"{max_temp:.1f} C"
                )

                print(
                    "KEYSIGHT OUTPUT OFF"
                )

                temperature_alarm(
                    max_temp
                )

                break


            # ================================================
            # CC-CV TERMINATION
            #
            # We terminate ONLY when:
            #
            # 1. Cell is at/near CV target
            # 2. Current <= 0.05C = 0.70 A
            # 3. Condition persists for 3 seconds
            # ================================================

            voltage_at_cv = (
                sense_voltage
                >= TARGET_VOLTAGE_V
                - CV_VOLTAGE_TOLERANCE_V
            )

            current_below_limit = (
                measured_current
                <= TERMINATION_CURRENT_A
            )


            if (
                voltage_at_cv
                and
                current_below_limit
            ):

                if termination_start is None:

                    termination_start = (
                        time.perf_counter()
                    )

                termination_elapsed = (
                    time.perf_counter()
                    - termination_start
                )


                if (
                    termination_elapsed
                    >= TERMINATION_HOLD_TIME_S
                ):

                    stop_reason = (
                        f"CC-CV complete: "
                        f"I <= {TERMINATION_CURRENT_A:.2f} A "
                        f"for {TERMINATION_HOLD_TIME_S:.1f} s"
                    )

                    # OUTPUT OFF IMMEDIATELY
                    supply.write(
                        "OUTP OFF"
                    )

                    print(
                        "\n\nCHARGE COMPLETE"
                    )

                    print(
                        f"Sense voltage = "
                        f"{sense_voltage:.4f} V"
                    )

                    print(
                        f"Termination current = "
                        f"{measured_current:.3f} A"
                    )

                    print(
                        f"Charge capacity = "
                        f"{charge_capacity_Ah:.4f} Ah"
                    )

                    print(
                        "KEYSIGHT OUTPUT OFF"
                    )

                    break


            else:

                # Condition was broken:
                # reset debounce timer
                termination_start = None


            # ================================================
            # APPROXIMATE LOG RATE
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
# PROGRAM / COMMUNICATION ERROR
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
# ALWAYS FORCE KEYSIGHT OUTPUT OFF
# ============================================================

finally:

    if supply is not None:

        try:

            supply.write(
                "OUTP OFF"
            )

            print(
                "\nKEYSIGHT OUTPUT OFF."
            )

        except Exception as error:

            print(
                "\nWARNING: Could not confirm "
                "Keysight output OFF!"
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


    if supply is not None:

        try:
            supply.close()
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
print("              CHARGE TEST COMPLETE")
print("============================================")

print(
    f"Stop reason:          "
    f"{stop_reason}"
)

print(
    f"Charge time:          "
    f"{charge_elapsed:.1f} s"
)

print(
    f"Charged capacity:     "
    f"{charge_capacity_Ah:.4f} Ah"
)

print(
    f"Final sense voltage:  "
    f"{sense_voltage:.4f} V"
)

print(
    f"Final myDAQ voltage:  "
    f"{mydaq_voltage:.4f} V"
)

print(
    f"Final current:        "
    f"{measured_current:.3f} A"
)

print(
    f"CSV saved to:\n"
    f"{CSV_FILE}"
)

print("============================================")