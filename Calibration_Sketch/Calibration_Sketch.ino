#include "HX711.h"

// Define pins matching your wiring
const int LOADCELL_DOUT_PIN = 3;
const int LOADCELL_SCK_PIN = 2;

HX711 scale;

// Your exact known weight
float known_weight = 243.0; 

void setup() {
  // Start the serial communication
  Serial.begin(9600);
  Serial.println("Starting HX711 Calibration...");

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  
  // Set scale to 1 so we get the pure, raw electrical data
  scale.set_scale(1);
  
  Serial.println("\nSTEP 1: Empty the scale completely.");
  Serial.println("Waiting 5 seconds...");
  delay(5000);
  
  Serial.println("\nSTEP 2: Zeroing the scale... Do not touch it.");
  scale.tare();
  Serial.println("Zeroing complete!");
  
  Serial.println("\nSTEP 3: Place your 243g weight on the scale NOW.");
  Serial.println("You have 10 seconds to place it and take your hands away...");
  delay(10000); 
  
  Serial.println("\nSTEP 4: Calculating...");
  // Get an average of 20 readings for extreme accuracy
  long raw_value = scale.get_units(20); 
  
  Serial.print("Raw Electrical Value: ");
  Serial.println(raw_value);
  
  // Calculate the final factor
  float final_calibration = (float)raw_value / known_weight;
  
  Serial.println("\n===========================================");
  Serial.print("SUCCESS! Your Calibration Factor is: ");
  Serial.println(final_calibration);
  Serial.println("===========================================");
  Serial.println("Write this number down. You will use it in your final code.");
}

void loop() {
  // We leave this empty because calibration only needs to run once.
}
