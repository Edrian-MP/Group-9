#include "HX711.h"

// Define pins
const int LOADCELL_DOUT_PIN = 3;
const int LOADCELL_SCK_PIN = 2;

HX711 scale;

// PUT YOUR ACCURATE REFERENCE UNIT HERE (e.g., 70.04)
float calibration_factor = 142.64; 

void setup() {
  Serial.begin(9600);
  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  
  scale.set_scale(calibration_factor);
  scale.tare(); // Auto-zero on startup
}

void loop() {
  if (scale.is_ready()) {
    // Send the weight over USB to the Pi
    Serial.println(scale.get_units(5), 2); 
  }
  delay(200); // Send data 5 times a second
}
