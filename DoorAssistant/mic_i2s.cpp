#include "mic_i2s.h"
#include "driver/i2s.h"

static const i2s_port_t I2S_MIC_PORT = I2S_NUM_1;

bool I2SMic::begin(int bclkPin, int wsPin, int dinPin, int sampleRate) {
  sampleRate_ = sampleRate;

  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  cfg.sample_rate = sampleRate_;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT; // common for I2S mics
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = false;
  cfg.fixed_mclk = 0;

  i2s_pin_config_t pins = {};
  pins.bck_io_num = bclkPin;
  pins.ws_io_num = wsPin;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = dinPin;

  if (i2s_driver_install(I2S_MIC_PORT, &cfg, 0, nullptr) != ESP_OK) return false;
  if (i2s_set_pin(I2S_MIC_PORT, &pins) != ESP_OK) return false;
  if (i2s_zero_dma_buffer(I2S_MIC_PORT) != ESP_OK) return false;

  return true;
}

bool I2SMic::record1s(int16_t* out, int sampleRate) {
  if (!out || sampleRate <= 0) return false;

  const size_t needSamples = (size_t)sampleRate;
  size_t written = 0;

  int32_t rx[256];
  while (written < needSamples) {
    size_t bytesRead = 0;
    if (i2s_read(I2S_MIC_PORT, rx, sizeof(rx), &bytesRead, portMAX_DELAY) != ESP_OK) {
      return false;
    }

    size_t n = bytesRead / sizeof(int32_t);
    for (size_t i = 0; i < n && written < needSamples; i++) {
      // Typical I2S mic: 24-bit left-justified in 32-bit container
      out[written++] = (int16_t)(rx[i] >> 16);
    }
  }

  return true;
}
