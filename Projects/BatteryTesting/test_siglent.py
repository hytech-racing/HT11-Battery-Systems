import pyvisa

RESOURCE = "USB0::0xF4EC::0x1621::SDL13GCD4R0583::INSTR"

rm = pyvisa.ResourceManager()

sdl = rm.open_resource(
    RESOURCE,
    open_timeout=3000
)

sdl.timeout = 3000

print(sdl.query("*IDN?").strip())

# Safety: ensure load is OFF
sdl.write(":SOURce:INPut:STATe OFF")

# Read current cell voltage
voltage = sdl.query("MEASure:VOLTage:DC?").strip()
print("Measured voltage:", voltage, "V")

# Configure CC mode
sdl.write(":SOURce:FUNCtion CURRent")

# Set 4.67 A
sdl.write(":SOURce:CURRent:LEVel:IMMediate 4.67")

print("CC mode configured")
print("Current setpoint = 4.67 A")
print("LOAD IS STILL OFF")

sdl.close()
rm.close()