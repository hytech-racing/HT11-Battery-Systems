import pyvisa


# ============================================================
# SETTINGS
# ============================================================

TARGET_MODEL = "E36231A"


# ============================================================
# CONNECT
# ============================================================

print("Searching for Keysight E36231A...")

rm = pyvisa.ResourceManager()

resources = rm.list_resources()

print("\nVISA resources:")
for resource in resources:
    print("  ", resource)

supply = None
resource_used = None


# ============================================================
# FIND KEYSIGHT
# ============================================================

for resource in resources:

    # Skip Arduino serial port
    if resource.startswith("ASRL"):
        continue

    try:
        instrument = rm.open_resource(
            resource,
            open_timeout=3000
        )

        instrument.timeout = 3000

        idn = instrument.query("*IDN?").strip()

        print(f"\n{resource}")
        print(f"ID: {idn}")

        if (
            "KEYSIGHT" in idn.upper()
            and TARGET_MODEL in idn.upper()
        ):
            supply = instrument
            resource_used = resource
            break

        instrument.close()

    except Exception as e:
        print(f"Could not query {resource}: {e}")


if supply is None:
    rm.close()
    raise RuntimeError(
        "Keysight E36231A not found."
    )


# ============================================================
# SAFETY: OUTPUT OFF
# ============================================================

print("\nKeysight found.")

supply.write("OUTP OFF")

print("OUTPUT OFF command sent.")


# ============================================================
# IDENTIFICATION
# ============================================================

idn = supply.query("*IDN?").strip()

print("\nInstrument:")
print(idn)

print("\nVISA resource:")
print(resource_used)


# ============================================================
# ENABLE 4-WIRE REMOTE SENSE
# ============================================================

print("\nEnabling external/4-wire sense...")

supply.write(
    "VOLT:SENS:SOUR EXT"
)

sense_mode = supply.query(
    "VOLT:SENS:SOUR?"
).strip()

print(
    f"Sense mode = {sense_mode}"
)


# ============================================================
# MEASURE VOLTAGE
# ============================================================

voltage = float(
    supply.query(
        "MEAS:VOLT?"
    )
)

print(
    f"\nMeasured sense voltage = "
    f"{voltage:.6f} V"
)


# ============================================================
# MEASURE CURRENT
# ============================================================

current = float(
    supply.query(
        "MEAS:CURR?"
    )
)

print(
    f"Measured current = "
    f"{current:.6f} A"
)


# ============================================================
# READ PROGRAMMED SETTINGS
# ============================================================

programmed_voltage = float(
    supply.query(
        "VOLT?"
    )
)

programmed_current = float(
    supply.query(
        "CURR?"
    )
)

print(
    f"\nProgrammed voltage = "
    f"{programmed_voltage:.6f} V"
)

print(
    f"Programmed current = "
    f"{programmed_current:.6f} A"
)


# ============================================================
# VERIFY OUTPUT STATE
# ============================================================

output_state = supply.query(
    "OUTP?"
).strip()

print(
    f"\nOutput state = "
    f"{output_state}"
)

if output_state in ["0", "OFF"]:
    print("Confirmed: OUTPUT IS OFF.")
else:
    print(
        "WARNING: Output state did not "
        "report OFF."
    )


# ============================================================
# CLEANUP
# ============================================================

supply.write("OUTP OFF")

supply.close()
rm.close()

print("\nTest complete.")
print("Keysight output remains OFF.")