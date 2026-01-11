#include "kws_model_data.h"

// Placeholder bytes: NOT a real .tflite model.
// Replace with your converted .tflite array.
const unsigned char g_model[] = {
  0x54, 0x46, 0x4C, 0x33, // "TFL3" signature often seen near the start of TFLite files
  0x00, 0x00, 0x00, 0x00
};

const int g_model_len = sizeof(g_model);