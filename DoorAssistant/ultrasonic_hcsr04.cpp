#include "ultrasonic_hcsr04.h"

void HCSR04::begin(int trigPin, int echoPin) {
  trig_ = trigPin;
  echo_ = echoPin;

  pinMode(trig_, OUTPUT);
  pinMode(echo_, INPUT);
  digitalWrite(trig_, LOW);
}

float HCSR04::readCm(uint32_t timeoutUs) {
  digitalWrite(trig_, LOW);
  delayMicroseconds(2);
  digitalWrite(trig_, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig_, LOW);

  unsigned long us = pulseIn(echo_, HIGH, timeoutUs);
  if (us == 0) return -1.0f;

  // cm = (time_us * 0.0343) / 2
  return (us * 0.0343f) * 0.5f;
}
