#pragma once
#include <Arduino.h>
#include <stdint.h>

struct KwsResult {
  int index;      // class index, or -1 on error
  uint8_t score;  // rough 0..255 confidence for argmax class
};

class KwsTflm {
public:
  // labels/labelCount should match your model output order
  bool begin(const char* const* labels, int labelCount);

  // Runs inference on exactly 1 second of 16kHz audio (int16 PCM).
  // For micro_speech-style models: input features are 49x40 int8.
  KwsResult run1s(const int16_t* pcm16_1s, int sampleRate);

  const char* label(int idx) const;

private:
  const char* const* labels_ = nullptr;
  int labelCount_ = 0;
};
