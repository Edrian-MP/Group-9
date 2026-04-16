import RPi.GPIO as GPIO
import time

class HX711:
    def __init__(self, dout, pd_sck, gain=128):
        self.PD_SCK = pd_sck
        self.DOUT = dout

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.PD_SCK, GPIO.OUT)
        GPIO.setup(self.DOUT, GPIO.IN)

        self.GAIN = 0
        self.REFERENCE_UNIT = 1  
        self.OFFSET = 1
        self.lastVal = 0

        self.byte_format = 'MSB'
        self.bit_format = 'MSB'

        self.set_gain(gain)

    def set_gain(self, gain):
        if gain == 128:
            self.GAIN = 1
        elif gain == 64:
            self.GAIN = 3
        elif gain == 32:
            self.GAIN = 2

        GPIO.output(self.PD_SCK, False)
        # We try to read, but catch errors to prevent init crash
        try:
            self.read()
        except Exception:
            pass

    def set_reading_format(self, byte_format="MSB", bit_format="MSB"):
        self.byte_format = byte_format
        self.bit_format = bit_format

    def set_reference_unit(self, reference_unit):
        self.REFERENCE_UNIT = reference_unit

    def convertFromTwosComplement24bit(self, inputValue):
        return -(inputValue & 0x800000) + (inputValue & 0x7FFFFF)

    def is_ready(self):
        return GPIO.input(self.DOUT) == 0

    def read(self):
        # Wait max 1 second for the scale to be ready.
        # If it takes longer, we raise an error so the App doesn't freeze.
        start_time = time.time()
        while not self.is_ready():
            if time.time() - start_time > 1.0: # 1 Second Timeout
                raise TimeoutError("HX711 Sensor not responding (Timeout)")
            time.sleep(0.001) # Give CPU a tiny break

        dataBits = [0, 0, 0]

        for j in range(2, -1, -1):
            for i in range(7, -1, -1):
                GPIO.output(self.PD_SCK, True)
                dataBits[j] |= (GPIO.input(self.DOUT) << i)
                GPIO.output(self.PD_SCK, False)

        for i in range(self.GAIN):
            GPIO.output(self.PD_SCK, True)
            GPIO.output(self.PD_SCK, False)

        if self.byte_format == 'LSB':
            dataBits = dataBits[::-1]
            
        dataVal = (dataBits[0] << 16) | (dataBits[1] << 8) | dataBits[2]
        dataVal = self.convertFromTwosComplement24bit(dataVal)

        self.lastVal = dataVal
        return dataVal

    def read_average(self, times=3):
        sum_val = 0
        success_count = 0
        for i in range(times):
            try:
                sum_val += self.read()
                success_count += 1
            except Exception:
                pass # Skip failed reads
        
        if success_count == 0:
            raise TimeoutError("Could not read from scale")
            
        return sum_val / success_count

    def get_value(self, times=3):
        return self.read_average(times) - self.OFFSET

    def get_weight(self, times=3):
        value = self.get_value(times)
        value = value / self.REFERENCE_UNIT
        return value

    def tare(self, times=15):
        # Try to tare, but if it fails (timeout), just set offset to 0
        try:
            sum_val = self.read_average(times)
            self.set_offset(sum_val)
        except Exception:
            print("[Warning] Scale Tare failed. Sensor might be disconnected.")
            self.set_offset(0)

    def set_offset(self, offset):
        self.OFFSET = offset

    def reset(self):
        self.power_down()
        self.power_up()

    def power_down(self):
        GPIO.output(self.PD_SCK, False)
        GPIO.output(self.PD_SCK, True)
        time.sleep(0.0001)

    def power_up(self):
        GPIO.output(self.PD_SCK, False)
        time.sleep(0.0001)
