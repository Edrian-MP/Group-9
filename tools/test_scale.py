import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from drivers.scale_driver import SmartScale

# Replace 5 and 6 with the BCM GPIO pins you actually wired DT and SCK to
DT_PIN = 5
SCK_PIN = 6

print("Initializing Scale...")
# This will use your existing SmartScale class and config.py defaults
scale = SmartScale(port='/dev/ttyACM0')

try:
    print("Tare (Zeroing) scale. Please ensure it's empty...")
    scale.tare()
    time.sleep(2)
    print("Ready! Place an item on the scale.")
    
    while True:
        # get_weight() is constantly updated by the background thread in SmartScale
        weight = scale.get_weight()
        print(f"Current Weight Reading: {weight:.2f}")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nTest stopped.")
finally:
    scale.stop()
