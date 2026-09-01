import nidaqmx
import time

DAQ_CHANNEL = "myDAQ1/ai0"

with nidaqmx.Task() as task:
    task.ai_channels.add_ai_voltage_chan(
        DAQ_CHANNEL,
        min_val=0.0,
        max_val=5.0
    )

    print("Reading myDAQ voltage...")
    print("Press CTRL+C to stop.\n")

    try:
        while True:
            voltage = task.read()

            print(
                f"\rVoltage = {voltage:.5f} V",
                end=""
            )

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nStopped.")