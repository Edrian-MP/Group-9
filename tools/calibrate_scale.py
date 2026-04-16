import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from drivers.hx711 import HX711

DT_PIN = 5
SCK_PIN = 6

# The exact weight of your test item. 
# We'll use grams here (220) so your scale outputs in grams.
KNOWN_WEIGHT = 243

print("Initializing Raw HX711...")
hx = HX711(dout=DT_PIN, pd_sck=SCK_PIN)
hx.set_reading_format("MSB", "MSB")

# Set reference unit to 1 so we get the pure RAW data from the sensor
hx.set_reference_unit(1)
hx.reset()

print("Empty the scale completely.")
time.sleep(2)
print("Tare (Zeroing)...")
hx.tare()
print("Tare complete.")

print(f"\nPlace your {KNOWN_WEIGHT}g weight on the scale NOW.")
time.sleep(10) # Give you time to place it and let it settle

print("\nReading raw values...")
try:
    # Get an average of 15 readings for accuracy
    raw_value = hx.get_value(15)
    print(f"Raw Value Read: {raw_value}")
    
    if raw_value < 0:
        print("\n[WARNING] The raw value is NEGATIVE!")
        print("Please swap your Green and White wires, or flip the load cell over, then try again.")
    else:
        # Calculate the actual reference unit
        new_reference_unit = raw_value / KNOWN_WEIGHT
        print(f"\n[SUCCESS] Calibration Complete!")
        print(f"Your new Reference Unit is: {new_reference_unit}")
        print("\nNext Steps:")
        print(f"1. Open your config.py file.")
        print(f"2. Change SCALE_REFERENCE_UNIT = 420 to SCALE_REFERENCE_UNIT = {new_reference_unit}")

except Exception as e:
    print(f"Error during reading: {e}")
finally:
    # Cleanup
    import RPi.GPIO as GPIO
    GPIO.cleanup()
