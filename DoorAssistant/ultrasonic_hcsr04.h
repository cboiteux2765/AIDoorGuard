#pragma once
#include <Arduino.h>

class HCSR04 {
public:
  void begin(int trigPin, int echoPin);

  // Returns distance in cm, or -1.0f on timeout/no echo
  float readCm(uint32_t timeoutUs = 25000UL);

private:
  int trig_ = -1;
  int echo_ = -1;
};
