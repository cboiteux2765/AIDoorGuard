#pragma once
#include <stdint.h>

extern const uint8_t wheregoing_u8[];
extern const unsigned int wheregoing_u8_len;

// The audio format expected by speaker.playU8():
// - unsigned 8-bit PCM (0..255)
// - mono
// - sample rate must match what you set in speaker.begin(sampleRate, ...)
//   (e.g., 22050 Hz)
