#include "audio_vad.h"
#include <cmath>
#include <algorithm>

namespace xiaoyou {
namespace audio {

AudioVAD::AudioVAD(int sample_rate, float energy_threshold) 
    : sample_rate_(sample_rate), energy_threshold_(energy_threshold) {}

bool AudioVAD::is_speech(const int16_t* data, size_t length) {
    if (length == 0) return false;
    
    double energy = 0.0;
    // Calculate Root Mean Square (RMS) energy
    for (size_t i = 0; i < length; ++i) {
        // Normalize 16-bit PCM integer (-32768 to 32767) to float (-1.0 to 1.0)
        double sample = data[i] / 32768.0; 
        energy += sample * sample;
    }
    energy = std::sqrt(energy / length);
    
    return energy > energy_threshold_;
}

std::vector<int16_t> AudioVAD::remove_silence(const int16_t* data, size_t length, int frame_ms) {
    std::vector<int16_t> result;
    // Calculate number of samples per frame. e.g., 16000Hz * 30ms / 1000 = 480 samples.
    size_t samples_per_frame = (sample_rate_ * frame_ms) / 1000;
    
    if (samples_per_frame == 0) return result;

    // Optional: Pre-reserve memory to avoid reallocation overhead.
    result.reserve(length);

    for (size_t i = 0; i < length; i += samples_per_frame) {
        size_t frame_len = std::min(samples_per_frame, length - i);
        
        // If the frame has speech, we keep it.
        if (is_speech(data + i, frame_len)) {
            result.insert(result.end(), data + i, data + i + frame_len);
        }
    }
    
    // Shrink memory usage to actual size after trimming
    result.shrink_to_fit();
    return result;
}

} // namespace audio
} // namespace xiaoyou
