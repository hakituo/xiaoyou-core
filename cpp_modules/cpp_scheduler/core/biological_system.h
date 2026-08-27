#pragma once
#include <unordered_map>
#include <string>
#include <mutex>
#include <chrono>

namespace ai_scheduler {

struct Neurotransmitter {
    float dopamine = 0.5f;       // 0.0 - 1.0 (Curiosity, Motivation)
    float serotonin = 0.5f;      // 0.0 - 1.0 (Mood stability)
    float norepinephrine = 0.5f; // 0.0 - 1.0 (Alertness, Stress)
    float oxytocin = 0.5f;       // 0.0 - 1.0 (Trust, Social bonding)
    float cortisol = 0.3f;       // 0.0 - 1.0 (Stress / Threat)
};

struct BiologicalConfig {
    float baseline_dopamine = 0.6f;
    float baseline_serotonin = 0.7f;
    float baseline_norepinephrine = 0.5f;
    float baseline_oxytocin = 0.5f;
    float baseline_cortisol = 0.3f;

    float decay_rate = 0.001f; // per second

    float energy_awake_decay = 0.0001f;  // per second
    float energy_sleep_recover = 0.0005f; // per second

    float sleep_debt_awake_gain = 0.00020f;   // per second
    float sleep_debt_sleep_recover = 0.00060f; // per second

    float cognitive_base_delay = 0.5f;
    float cognitive_complexity_scale = 2.0f;
    float cognitive_energy_scale = 2.0f;
    float cognitive_dopamine_scale = 0.5f;
    float cognitive_serotonin_scale = 0.2f;
    float cognitive_cortisol_scale = 0.8f;
    float cognitive_sleep_debt_scale = 1.0f;
};

enum class CircadianPhase {
    WAKE,
    ACTIVE,
    TIRED,
    SLEEP,
    DREAMING
};

class BiologicalSystem {
public:
    BiologicalSystem();
    ~BiologicalSystem();

    void initialize();
    void update(float deltaTimeSeconds); // Called periodically

    // State Access
    Neurotransmitter getNeurotransmitters() const;
    void adjustNeurotransmitter(const std::string& name, float delta);
    
    float getEnergy() const; // 0.0 - 1.0
    void consumeEnergy(float amount);
    void recoverEnergy(float amount);

    float getSleepDebt() const; // 0.0 - 1.0
    
    CircadianPhase getCircadianPhase() const;
    
    // Cognitive Latency Calculation
    // complexity: 0.0 - 1.0
    // Returns seconds of delay
    float calculateCognitiveDelay(float complexity) const;

    BiologicalConfig getConfig() const;
    void setConfig(const BiologicalConfig& config);

private:
    void updateCircadianRhythm();
    void decayNeurotransmitters(float deltaTime);

    mutable std::mutex mutex_;
    Neurotransmitter neurotransmitters_;
    float energy_;
    float sleep_debt_;
    CircadianPhase phase_;
    
    std::chrono::system_clock::time_point lastUpdate_;
    
    BiologicalConfig config_;
};

} // namespace ai_scheduler
