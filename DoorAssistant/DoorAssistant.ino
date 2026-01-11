#include <Arduino.h>
#include "driver/i2s.h"

// ==========================
// Pins (edit to match yours)
// ==========================
static const int TRIG_PIN = 5;
static const int ECHO_PIN = 18;   // MUST be level-shifted to 3.3V

// I2S MIC pins (INMP441 / SPH0645, etc.)
static const int MIC_BCLK = 14;
static const int MIC_WS   = 15;
static const int MIC_SD   = 32;

// ==========================
// Ultrasonic settings
// ==========================
static const float THRESH_CM = 120.0f;

// Require N consecutive “near” measurements to trigger (noise reduction)
static const int NEAR_CONFIRM_COUNT = 3;

// After triggering, wait some time before allowing another trigger
static const uint32_t COOLDOWN_MS = 8000;

// Sample ultrasonic this often
static const uint32_t ULTRA_PERIOD_MS = 100;

// ==========================
// Audio settings (DAC prompt)
// ==========================
// NOTE: built-in DAC exists only on classic ESP32 (GPIO25/26).
static const i2s_port_t I2S_DAC_PORT = I2S_NUM_0;
static const int DAC_SAMPLE_RATE = 22050;

// ==========================
// Mic settings
// ==========================
static const i2s_port_t I2S_MIC_PORT = I2S_NUM_1;
static const int MIC_SAMPLE_RATE = 16000;

// Record 1 second for KWS (adjust if your model expects different)
static int16_t g_audio_1s[MIC_SAMPLE_RATE];

// ==========================
// State machine
// ==========================
enum State { IDLE, PROMPT, LISTEN, COOLDOWN };
static State g_state = IDLE;

static uint32_t g_lastUltraMs = 0;
static int g_nearCount = 0;
static uint32_t g_stateStartMs = 0;

// ==========================
// HC-SR04 read
// ==========================
float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Timeout 25ms ~ 4m max range
  unsigned long us = pulseIn(ECHO_PIN, HIGH, 25000UL);
  if (us == 0) return -1.0f;

  // cm = (time_us * 0.0343) / 2
  return (us * 0.0343f) / 2.0f;
}

// ==========================
// I2S DAC prompt (simple tone prompt)
// ==========================
static inline uint16_t s16_to_dac_word(int16_t s) {
  // Signed 16-bit PCM -> unsigned 8-bit for DAC (in high byte)
  uint8_t u = (uint8_t)((s >> 8) + 128);
  return ((uint16_t)u) << 8;
}

void setupI2SDAC_BuiltIn() {
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_DAC_BUILT_IN);
  cfg.sample_rate = DAC_SAMPLE_RATE;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT; // stereo frames
  cfg.communication_format = I2S_COMM_FORMAT_I2S_MSB;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = true;
  cfg.fixed_mclk = 0;

  i2s_driver_install(I2S_DAC_PORT, &cfg, 0, nullptr);
  i2s_set_pin(I2S_DAC_PORT, nullptr);
  i2s_set_dac_mode(I2S_DAC_CHANNEL_BOTH_EN); // GPIO25+26
  i2s_zero_dma_buffer(I2S_DAC_PORT);
}

void playTone(int freqHz, int ms, int16_t amp = 12000) {
  const int totalSamples = (DAC_SAMPLE_RATE * ms) / 1000;
  const int chunk = 256;
  static uint16_t out[chunk * 2]; // stereo words

  uint32_t phase = 0;
  uint32_t phaseInc = (uint32_t)((((uint64_t)freqHz) << 32) / DAC_SAMPLE_RATE);

  for (int i = 0; i < totalSamples; i += chunk) {
    int thisChunk = min(chunk, totalSamples - i);

    for (int n = 0; n < thisChunk; n++) {
      phase += phaseInc;
      // square wave (good enough for prompt beep)
      int16_t s = (phase & 0x80000000u) ? amp : -amp;
      uint16_t w = s16_to_dac_word(s);
      out[2 * n]     = w;
      out[2 * n + 1] = w;
    }

    size_t bytesWritten = 0;
    i2s_write(I2S_DAC_PORT, out, thisChunk * 2 * sizeof(uint16_t), &bytesWritten, portMAX_DELAY);
  }
}

// “Ask where are you going?” prompt (beeps)
// If you want actual speech, replace this with playback of a PCM/WAV clip.
void playWhereGoingPrompt() {
  playTone(880, 120);
  delay(70);
  playTone(660, 120);
  delay(70);
  playTone(880, 120);
}

// ==========================
// I2S Mic capture
// ==========================
void setupI2SMic() {
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  cfg.sample_rate = MIC_SAMPLE_RATE;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;     // many I2S mics output left
  cfg.communication_format = I2S_COMM_FORMAT_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = false;
  cfg.fixed_mclk = 0;

  i2s_pin_config_t pins = {};
  pins.bck_io_num   = MIC_BCLK;
  pins.ws_io_num    = MIC_WS;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num  = MIC_SD;

  i2s_driver_install(I2S_MIC_PORT, &cfg, 0, nullptr);
  i2s_set_pin(I2S_MIC_PORT, &pins);
  i2s_zero_dma_buffer(I2S_MIC_PORT);
}

bool record1sAudio() {
  size_t needBytes = sizeof(g_audio_1s);
  size_t gotTotal = 0;
  while (gotTotal < needBytes) {
    size_t got = 0;
    i2s_read(I2S_MIC_PORT, (uint8_t*)g_audio_1s + gotTotal, needBytes - gotTotal, &got, portMAX_DELAY);
    gotTotal += got;
  }
  return true;
}

// ==========================
// Keyword spotting hook
// ==========================
// Replace this with your real TFLite Micro inference function.
// Return label like "work", "gym", "store", "class", "other", or nullptr if nothing.
const char* runKeywordSpotting_1s(const int16_t* pcm16_1s, int sampleRate) {
  (void)pcm16_1s;
  (void)sampleRate;

  // TODO: call your TFLM interpreter here.
  // For now, stub:
  return "unknown";
}

// ==========================
// Setup + loop
// ==========================
void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  setupI2SMic();
  setupI2SDAC_BuiltIn();

  Serial.println("Ready: ultrasonic -> prompt -> KWS");
}

void loop() {
  const uint32_t now = millis();

  // ---- Periodic ultrasonic read ----
  if (now - g_lastUltraMs >= ULTRA_PERIOD_MS) {
    g_lastUltraMs = now;

    float cm = readDistanceCm();
    if (cm > 0) {
      Serial.printf("Distance: %.1f cm\n", cm);

      bool isNear = (cm <= THRESH_CM);
      if (isNear) g_nearCount++;
      else g_nearCount = 0;
    } else {
      // invalid read -> don't accumulate near count
      g_nearCount = 0;
    }
  }

  // ---- State machine ----
  switch (g_state) {
    case IDLE: {
      if (g_nearCount >= NEAR_CONFIRM_COUNT) {
        g_nearCount = 0;
        g_state = PROMPT;
        g_stateStartMs = now;
      }
      break;
    }

    case PROMPT: {
      // “signal speaker output to ask user where they're going”
      Serial.println("Prompting: Where are you going?");
      playWhereGoingPrompt();

      g_state = LISTEN;
      g_stateStartMs = now;
      break;
    }

    case LISTEN: {
      // Record 1 second audio and run KWS once (simple MVP)
      Serial.println("Listening for destination keyword...");
      record1sAudio();

      const char* label = runKeywordSpotting_1s(g_audio_1s, MIC_SAMPLE_RATE);
      Serial.printf("KWS result: %s\n", label ? label : "(none)");

      // You can add logic: if label is "unknown"/"silence", retry a few times before cooldown
      g_state = COOLDOWN;
      g_stateStartMs = now;
      break;
    }

    case COOLDOWN: {
      if (now - g_stateStartMs >= COOLDOWN_MS) {
        g_state = IDLE;
      }
      break;
    }
  }
}
