#pragma once
#include <Arduino.h>

class DacSpeaker {
public:
  // Classic ESP32 only: DAC pins are GPIO25 (DAC1) or GPIO26 (DAC2)
  // sampleRate: e.g., 22050
  bool begin(int sampleRate, int dacGpio = 25);

  // Play unsigned 8-bit PCM (0..255) at sampleRate
  void playU8(const uint8_t* pcm, size_t n);

  // Debug beep
  void playTone(int freqHz, int ms, int16_t amp = 12000);

private:
  int sampleRate_ = 22050;
  int dacGpio_ = 25;
};