#include <Arduino.h>
#include <math.h>

// Thermistor parameters
#define RT0 10000.0      // Resistance at 25°C (10kΩ)
#define B   3950.0       // Beta coefficient
#define R   6800.0       // Fixed resistor (6.8kΩ)
#define VCC 5.0          // Supply voltage

// Reference temperature (25°C in Kelvin)
const float T0 = 25.0 + 273.15;

// Read a thermistor and return temperature in Celsius
float readThermistor(int pin) {
  int adc = analogRead(pin);

  // Prevent divide-by-zero errors
  if (adc <= 0 || adc >= 1023) {
    return NAN;
  }

  // Voltage across thermistor
  float VRT = (VCC * adc) / 1023.0;

  // Voltage across fixed resistor
  float VR = VCC - VRT;

  // Thermistor resistance
  float RT = VRT / (VR / R);

  // Beta equation
  float lnRT = log(RT / RT0);
  float tempK = 1.0 / ((lnRT / B) + (1.0 / T0));

  // Return Celsius
  return tempK - 273.15;
}

void setup() {
  Serial.begin(9600);
}

void loop() {

  // Read all thermistors
  float T1 = readThermistor(A0);
  float T2 = readThermistor(A1);
  float T3 = readThermistor(A2);
  float T4 = readThermistor(A3);

  Serial.print("T1 (ambient): ");
  if (isnan(T1))
    Serial.print("ERR");
  else
    Serial.print(T1, 1);

  Serial.print(" C | ");

  Serial.print("T2 (body): ");
  if (isnan(T2))
    Serial.print("ERR");
  else
    Serial.print(T2, 1);

  Serial.print(" C | ");

  Serial.print("T3 (negative tab): ");
  if (isnan(T3))
    Serial.print("ERR");
  else
    Serial.print(T3, 1);

  Serial.print(" C | ");

  Serial.print("T4 (positive tab): ");
  if (isnan(T4))
    Serial.print("ERR");
  else
    Serial.print(T4, 1);

  Serial.println(" C");

  delay(500);
}