#pragma once
#include <Arduino.h>

class I2SMic {
public:
  // bclk/ws/din: your I2S mic pins
  // sampleRate: usually 16000 for KWS
  bool begin(int bclkPin, int wsPin, int dinPin, int sampleRate = 16000);

  // Record exactly 1 second into out[] (length must be sampleRate)
  bool record1s(int16_t* out, int sampleRate);

private:
  int sampleRate_ = 16000;
};
