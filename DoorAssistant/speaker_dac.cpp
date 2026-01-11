#include "speaker_dac.h"
#include "driver/i2s.h"

static const i2s_port_t I2S_DAC_PORT = I2S_NUM_0;

static inline uint16_t u8_to_dac_word(uint8_t u) {
  return ((uint16_t)u) << 8; // DAC uses high 8 bits
}

static inline uint16_t s16_to_dac_word(int16_t s) {
  uint8_t u = (uint8_t)((s >> 8) + 128);
  return u8_to_dac_word(u);
}

bool DacSpeaker::begin(int sampleRate, int dacGpio) {
  sampleRate_ = sampleRate;
  dacGpio_ = dacGpio;

  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX | I2S_MODE_DAC_BUILT_IN);
  cfg.sample_rate = sampleRate_;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT; // mono
  cfg.communication_format = I2S_COMM_FORMAT_I2S_MSB;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = true;
  cfg.fixed_mclk = 0;

  if (i2s_driver_install(I2S_DAC_PORT, &cfg, 0, nullptr) != ESP_OK) return false;
  if (i2s_set_pin(I2S_DAC_PORT, nullptr) != ESP_OK) return false;

  if (dacGpio_ == 25) {
    i2s_set_dac_mode(I2S_DAC_CHANNEL_LEFT_EN);
  } else if (dacGpio_ == 26) {
    i2s_set_dac_mode(I2S_DAC_CHANNEL_RIGHT_EN);
  } else {
    return false;
  }

  i2s_zero_dma_buffer(I2S_DAC_PORT);
  return true;
}

void DacSpeaker::playU8(const uint8_t* pcm, size_t n) {
  if (!pcm || n == 0) return;

  uint16_t buf[256];
  size_t idx = 0;

  while (idx < n) {
    size_t chunk = min((size_t)256, n - idx);
    for (size_t i = 0; i < chunk; i++) {
      buf[i] = u8_to_dac_word(pcm[idx + i]);
    }

    size_t bytesWritten = 0;
    i2s_write(I2S_DAC_PORT, buf, chunk * sizeof(uint16_t), &bytesWritten, portMAX_DELAY);
    idx += chunk;
  }
}

void DacSpeaker::playTone(int freqHz, int ms, int16_t amp) {
  if (freqHz <= 0 || ms <= 0) return;

  const int totalSamples = (sampleRate_ * ms) / 1000;
  const int chunk = 256;
  uint16_t out[chunk];

  uint32_t phase = 0;
  const uint32_t phaseInc =
      (uint32_t)((((uint64_t)freqHz) << 32) / (uint32_t)sampleRate_);

  for (int i = 0; i < totalSamples; i += chunk) {
    int thisChunk = min(chunk, totalSamples - i);
    for (int n = 0; n < thisChunk; n++) {
      phase += phaseInc;
      int16_t s = (phase & 0x80000000u) ? amp : -amp; // square wave
      out[n] = s16_to_dac_word(s);
    }
    size_t bytesWritten = 0;
    i2s_write(I2S_DAC_PORT, out, thisChunk * sizeof(uint16_t), &bytesWritten, portMAX_DELAY);
  }
}
