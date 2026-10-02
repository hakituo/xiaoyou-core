#pragma once

#include <vector>
#include <cstdint>
#include <cstddef>

namespace xiaoyou {
namespace audio {

class AudioVAD {
public:
    // Initialize VAD with expected sample rate and RMS energy threshold.
    // E.g., sample_rate = 16000, energy_threshold = 0.05
    AudioVAD(int sample_rate, float energy_threshold);
    ~AudioVAD() = default;
    
    // Checks if a specific chunk of PCM int16 audio contains speech.
    bool is_speech(const int16_t* data, size_t length);
    
    // Processes a full audio array, divides it into frames (e.g., 30ms),
    // and returns a new array with silence frames removed.
    std::vector<int16_t> remove_silence(const int16_t* data, size_t length, int frame_ms = 30);

private:
    int sample_rate_;
    float energy_threshold_;
};

} // namespace audio
} // namespace xiaoyou
