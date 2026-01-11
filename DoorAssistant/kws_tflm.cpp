// IMPORTANT: keep this include first in this .cpp on ESP32 Arduino
#include <TensorFlowLite_ESP32.h>

#include "kws_tflm.h"

// TFLM core
#include "tensorflow/lite/schema/schema_generated.h"
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/version.h"

// micro_speech frontend (MFCC-ish features)
#include "tensorflow/lite/micro/examples/micro_speech/micro_features/micro_features_generator.h"
#include "tensorflow/lite/micro/examples/micro_speech/micro_features/micro_model_settings.h"

// Your model bytes (you provide these generated files)
#include "kws_model_data.h"

static tflite::MicroErrorReporter g_error_reporter;
static tflite::ErrorReporter* g_er = &g_error_reporter;

static const tflite::Model* g_model_ptr = nullptr;
static tflite::MicroInterpreter* g_interpreter = nullptr;
static TfLiteTensor* g_input = nullptr;
static TfLiteTensor* g_output = nullptr;

// Increase if AllocateTensors fails
static constexpr int kArenaSize = 140 * 1024;
static uint8_t g_arena[kArenaSize];

// Feature buffer: 49 slices * 40 bins = 1960 bytes
static int8_t g_features[kFeatureElementCount];

bool KwsTflm::begin(const char* const* labels, int labelCount) {
  labels_ = labels;
  labelCount_ = labelCount;

  g_model_ptr = tflite::GetModel(g_model);
  if (!g_model_ptr) return false;
  if (g_model_ptr->version() != TFLITE_SCHEMA_VERSION) return false;

  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(
      g_model_ptr, resolver, g_arena, kArenaSize, g_er);

  g_interpreter = &static_interpreter;

  if (g_interpreter->AllocateTensors() != kTfLiteOk) return false;

  g_input = g_interpreter->input(0);
  g_output = g_interpreter->output(0);

  if (!g_input || !g_output) return false;

  // micro_speech-style expects int8 input with exactly 1960 bytes
  if (g_input->type != kTfLiteInt8) return false;
  if (g_input->bytes != kFeatureElementCount) return false;

  return true;
}

KwsResult KwsTflm::run1s(const int16_t* pcm16_1s, int sampleRate) {
  KwsResult r{.index = -1, .score = 0};
  if (!pcm16_1s) return r;

  // This implementation matches micro_speech defaults: 16kHz input
  if (sampleRate != kAudioSampleFrequency) return r;

  if (InitializeMicroFeatures(g_er) != kTfLiteOk) return r;

  const int stride_samples = (kFeatureSliceStrideMs * kAudioSampleFrequency) / 1000;     // 320
  const int window_samples = (kFeatureSliceDurationMs * kAudioSampleFrequency) / 1000;  // 480

  for (int slice = 0; slice < kFeatureSliceCount; slice++) {
    const int start = slice * stride_samples;

    // Micro features code expects up to kMaxAudioSampleSize samples; we pad.
    int16_t slice_buf[kMaxAudioSampleSize];
    for (int i = 0; i < kMaxAudioSampleSize; i++) slice_buf[i] = 0;

    for (int i = 0; i < window_samples; i++) {
      int idx = start + i;
      if (idx >= 0 && idx < kAudioSampleFrequency) slice_buf[i] = pcm16_1s[idx];
    }

    int8_t* out_slice = g_features + (slice * kFeatureSliceSize);
    size_t samples_read = 0;

    if (GenerateMicroFeatures(g_er,
                              slice_buf,
                              kMaxAudioSampleSize,
                              kFeatureSliceSize,
                              out_slice,
                              &samples_read) != kTfLiteOk) {
      return r;
    }
  }

  memcpy(g_input->data.int8, g_features, kFeatureElementCount);

  if (g_interpreter->Invoke() != kTfLiteOk) return r;

  const int outN = g_output->dims->data[g_output->dims->size - 1];

  int best = 0;
  int8_t bestv = g_output->data.int8[0];
  for (int i = 1; i < outN; i++) {
    int8_t v = g_output->data.int8[i];
    if (v > bestv) { bestv = v; best = i; }
  }

  r.index = best;
  r.score = (uint8_t)((int)bestv + 128); // rough map [-128..127] -> [0..255]
  return r;
}

const char* KwsTflm::label(int idx) const {
  if (!labels_ || idx < 0 || idx >= labelCount_) return "?";
  return labels_[idx];
}
