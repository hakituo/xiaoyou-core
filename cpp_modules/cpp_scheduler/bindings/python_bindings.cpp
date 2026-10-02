#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>
#include "../core/resource_isolation_scheduler.h"
#include "../core/native_executor.h"
#include "../workers/gpu_llm_worker.h"
#include "../core/biological_system.h"
#include "../core/phase_strategy.h"

namespace py = pybind11;
using namespace ai_scheduler;

PYBIND11_MODULE(scheduler_py, m) {
    m.doc() = "AI Scheduler Python Bindings";

    // Enums
    py::enum_<TaskType>(m, "TaskType")
        .value("LLM_INFERENCE", TaskType::LLM_INFERENCE)
        .value("TTS_SYNTHESIS", TaskType::TTS_SYNTHESIS)
        .value("IMAGE_GENERATION", TaskType::IMAGE_GENERATION)
        .export_values();
        
    py::enum_<TaskStatus>(m, "TaskStatus")
        .value("PENDING", TaskStatus::PENDING)
        .value("RUNNING", TaskStatus::RUNNING)
        .value("COMPLETED", TaskStatus::COMPLETED)
        .value("FAILED", TaskStatus::FAILED)
        .value("CANCELLED", TaskStatus::CANCELLED)
        .export_values();

    // Structs
    py::class_<LLMInferenceRequest>(m, "LLMInferenceRequest")
        .def(py::init<>())
        .def_readwrite("prompt", &LLMInferenceRequest::prompt)
        .def_readwrite("conversationId", &LLMInferenceRequest::conversationId)
        .def_readwrite("maxTokens", &LLMInferenceRequest::maxTokens)
        .def_readwrite("temperature", &LLMInferenceRequest::temperature)
        .def_readwrite("topK", &LLMInferenceRequest::topK)
        .def_readwrite("topP", &LLMInferenceRequest::topP)
        .def_readwrite("repetitionPenalty", &LLMInferenceRequest::repetitionPenalty)
        .def_readwrite("streamOutput", &LLMInferenceRequest::streamOutput)
        .def_readwrite("onTokenGenerated", &LLMInferenceRequest::onTokenGenerated);

    py::class_<LLMInferenceResponse>(m, "LLMInferenceResponse")
        .def(py::init<>())
        .def_readwrite("generatedText", &LLMInferenceResponse::generatedText)
        .def_readwrite("generatedTokens", &LLMInferenceResponse::generatedTokens)
        .def_readwrite("inferenceTime", &LLMInferenceResponse::inferenceTime)
        .def_readwrite("success", &LLMInferenceResponse::success)
        .def_readwrite("errorMessage", &LLMInferenceResponse::errorMessage);

    // ITask
    py::class_<ITask, std::shared_ptr<ITask>>(m, "ITask")
        .def("getTaskId", &ITask::getTaskId)
        .def("getStatus", &ITask::getStatus);
        // getResult is void*, hard to map generic void* to python. 
        // Subclasses should expose specific results.

    // LLMTask
    py::class_<LLMTask, ITask, std::shared_ptr<LLMTask>>(m, "LLMTask")
        .def(py::init<const LLMInferenceRequest&>()) // Uses default worker=nullptr
        .def("getResponse", &LLMTask::getResponse)
        .def("getRequest", &LLMTask::getRequest, py::return_value_policy::reference_internal)
        .def("setResponse", &LLMTask::setResponse)
        .def("setErrorMessage", &LLMTask::setErrorMessage);

    // IWorker (needed for addWorker)
    py::class_<IWorker, std::shared_ptr<IWorker>>(m, "IWorker")
        .def("getWorkerId", &IWorker::getWorkerId);

    // GPULLMWorker
    py::class_<GPULLMWorker, IWorker, std::shared_ptr<GPULLMWorker>>(m, "GPULLMWorker")
        .def(py::init<const std::string&>())
        .def("initialize", &GPULLMWorker::initialize)
        .def("shutdown", &GPULLMWorker::shutdown)
        .def("setModelConfig", &GPULLMWorker::setModelConfig)
        .def("clearConversationCache", &GPULLMWorker::clearConversationCache);

    // LLMModelConfig
    py::class_<LLMModelConfig>(m, "LLMModelConfig")
        .def(py::init<>())
        .def_readwrite("modelPath", &LLMModelConfig::modelPath)
        .def_readwrite("modelType", &LLMModelConfig::modelType)
        .def_readwrite("quantization", &LLMModelConfig::quantization)
        .def_readwrite("gpu_device_id", &LLMModelConfig::gpuDeviceId)
        .def_readwrite("n_gpu_layers", &LLMModelConfig::nGpuLayers)
        .def_readwrite("max_context_size", &LLMModelConfig::maxContextSize)
        .def_readwrite("maxBatchSize", &LLMModelConfig::maxBatchSize)
        .def_readwrite("temperature", &LLMModelConfig::temperature)
        .def_readwrite("topK", &LLMModelConfig::topK)
        .def_readwrite("topP", &LLMModelConfig::topP)
        .def_readwrite("repetitionPenalty", &LLMModelConfig::repetitionPenalty)
        .def_readwrite("enableCache", &LLMModelConfig::enableCache)
        .def_readwrite("cacheSize", &LLMModelConfig::cacheSize)
        .def_readwrite("draftModelPath", &LLMModelConfig::draftModelPath)
        .def_readwrite("draftGpuDeviceId", &LLMModelConfig::draftGpuDeviceId)
        .def_readwrite("draftContextSize", &LLMModelConfig::draftContextSize)
        .def_readwrite("enableKvSwap", &LLMModelConfig::enableKvSwap)
        .def_readwrite("kvSwapDir", &LLMModelConfig::kvSwapDir)
        .def_readwrite("kvSwapTriggerTokens", &LLMModelConfig::kvSwapTriggerTokens);

    // Biological System Types
    py::class_<Neurotransmitter>(m, "Neurotransmitter")
        .def(py::init<>())
        .def_readwrite("dopamine", &Neurotransmitter::dopamine)
        .def_readwrite("serotonin", &Neurotransmitter::serotonin)
        .def_readwrite("norepinephrine", &Neurotransmitter::norepinephrine)
        .def_readwrite("oxytocin", &Neurotransmitter::oxytocin)
        .def_readwrite("cortisol", &Neurotransmitter::cortisol);

    py::class_<BiologicalConfig>(m, "BiologicalConfig")
        .def(py::init<>())
        .def_readwrite("baseline_dopamine", &BiologicalConfig::baseline_dopamine)
        .def_readwrite("baseline_serotonin", &BiologicalConfig::baseline_serotonin)
        .def_readwrite("baseline_norepinephrine", &BiologicalConfig::baseline_norepinephrine)
        .def_readwrite("baseline_oxytocin", &BiologicalConfig::baseline_oxytocin)
        .def_readwrite("baseline_cortisol", &BiologicalConfig::baseline_cortisol)
        .def_readwrite("decay_rate", &BiologicalConfig::decay_rate)
        .def_readwrite("energy_awake_decay", &BiologicalConfig::energy_awake_decay)
        .def_readwrite("energy_sleep_recover", &BiologicalConfig::energy_sleep_recover)
        .def_readwrite("sleep_debt_awake_gain", &BiologicalConfig::sleep_debt_awake_gain)
        .def_readwrite("sleep_debt_sleep_recover", &BiologicalConfig::sleep_debt_sleep_recover)
        .def_readwrite("cognitive_base_delay", &BiologicalConfig::cognitive_base_delay)
        .def_readwrite("cognitive_complexity_scale", &BiologicalConfig::cognitive_complexity_scale)
        .def_readwrite("cognitive_energy_scale", &BiologicalConfig::cognitive_energy_scale)
        .def_readwrite("cognitive_dopamine_scale", &BiologicalConfig::cognitive_dopamine_scale)
        .def_readwrite("cognitive_serotonin_scale", &BiologicalConfig::cognitive_serotonin_scale)
        .def_readwrite("cognitive_cortisol_scale", &BiologicalConfig::cognitive_cortisol_scale)
        .def_readwrite("cognitive_sleep_debt_scale", &BiologicalConfig::cognitive_sleep_debt_scale);

    py::enum_<CircadianPhase>(m, "CircadianPhase")
        .value("WAKE", CircadianPhase::WAKE)
        .value("ACTIVE", CircadianPhase::ACTIVE)
        .value("TIRED", CircadianPhase::TIRED)
        .value("SLEEP", CircadianPhase::SLEEP)
        .value("DREAMING", CircadianPhase::DREAMING)
        .export_values();

    py::class_<BiologicalSystem, std::shared_ptr<BiologicalSystem>>(m, "BiologicalSystem")
        .def("initialize", &BiologicalSystem::initialize)
        .def("update", &BiologicalSystem::update)
        .def("getNeurotransmitters", &BiologicalSystem::getNeurotransmitters)
        .def("adjustNeurotransmitter", &BiologicalSystem::adjustNeurotransmitter)
        .def("getEnergy", &BiologicalSystem::getEnergy)
        .def("consumeEnergy", &BiologicalSystem::consumeEnergy)
        .def("recoverEnergy", &BiologicalSystem::recoverEnergy)
        .def("getSleepDebt", &BiologicalSystem::getSleepDebt)
        .def("getCircadianPhase", &BiologicalSystem::getCircadianPhase)
        .def("calculateCognitiveDelay", &BiologicalSystem::calculateCognitiveDelay)
        .def("getConfig", &BiologicalSystem::getConfig)
        .def("setConfig", &BiologicalSystem::setConfig);

    // NativeExecutor
    py::class_<NativeExecutor, std::shared_ptr<NativeExecutor>>(m, "NativeExecutor")
        .def("executeAsync", &NativeExecutor::executeAsync)
        .def("addTimer", &NativeExecutor::addTimer)
        .def("isRunning", &NativeExecutor::isRunning);

    // ResourceIsolationScheduler
    py::class_<ResourceIsolationScheduler::SystemStatus>(m, "SystemStatus")
        .def_readwrite("totalTasks", &ResourceIsolationScheduler::SystemStatus::totalTasks)
        .def_readwrite("pendingTasks", &ResourceIsolationScheduler::SystemStatus::pendingTasks)
        .def_readwrite("runningTasks", &ResourceIsolationScheduler::SystemStatus::runningTasks)
        .def_readwrite("completedTasks", &ResourceIsolationScheduler::SystemStatus::completedTasks)
        .def_readwrite("failedTasks", &ResourceIsolationScheduler::SystemStatus::failedTasks)
        .def_readwrite("workerStatus", &ResourceIsolationScheduler::SystemStatus::workerStatus);

    py::class_<ResourceIsolationScheduler::ResourceUsage>(m, "ResourceUsage")
        .def_readwrite("cpuUsage", &ResourceIsolationScheduler::ResourceUsage::cpuUsage)
        .def_readwrite("gpuUsage", &ResourceIsolationScheduler::ResourceUsage::gpuUsage)
        .def_readwrite("memoryUsage", &ResourceIsolationScheduler::ResourceUsage::memoryUsage)
        .def_readwrite("gpuMemoryUsage", &ResourceIsolationScheduler::ResourceUsage::gpuMemoryUsage);

    py::class_<ResourceIsolationScheduler, std::shared_ptr<ResourceIsolationScheduler>>(m, "ResourceIsolationScheduler")
        .def(py::init<>())
        .def("initialize", &ResourceIsolationScheduler::initialize, py::arg("cpuThreadCount") = 4)
        .def("setNativeExecutorEnabled", &ResourceIsolationScheduler::setNativeExecutorEnabled)
        .def("setBiologicalUpdateIntervalMs", &ResourceIsolationScheduler::setBiologicalUpdateIntervalMs)
        .def("getBiologicalUpdateCount", &ResourceIsolationScheduler::getBiologicalUpdateCount)
        .def("shutdown", &ResourceIsolationScheduler::shutdown)
        .def(
            "submitTask",
            [](ResourceIsolationScheduler& scheduler, std::shared_ptr<ITask> task) {
                scheduler.submitTask(std::move(task));
            }
        )
        .def("cancelTask", &ResourceIsolationScheduler::cancelTask)
        .def("getTaskStatus", &ResourceIsolationScheduler::getTaskStatus)
        .def("getTask", &ResourceIsolationScheduler::getTask)
        .def("addWorker", &ResourceIsolationScheduler::addWorker)
        .def("getBiologicalSystem", &ResourceIsolationScheduler::getBiologicalSystem)
        .def("getNativeExecutor", &ResourceIsolationScheduler::getNativeExecutor)
        .def("getSystemStatus", &ResourceIsolationScheduler::getSystemStatus)
        .def("getResourceUsage", &ResourceIsolationScheduler::getResourceUsage)
        .def("submit_phase_task", &ResourceIsolationScheduler::submitPhaseTask)
        .def("set_phase_strategy", &ResourceIsolationScheduler::setPhaseStrategy)
        .def("get_phase_strategy", &ResourceIsolationScheduler::getPhaseStrategy)
        .def("get_llm_state", &ResourceIsolationScheduler::getLLMState)
        .def("migrate_llm_to_cpu", &ResourceIsolationScheduler::migrateLLMToCPU, py::arg("urgent") = false)
        .def("restore_llm_to_gpu", &ResourceIsolationScheduler::restoreLLMToGPU)
        .def("set_migration_callbacks", &ResourceIsolationScheduler::setMigrationCallbacks);

    // ============================================================
    // Phase-Aware Scheduling 绑定（统一 phase_strategy.h）
    // ============================================================

    // Phase-Aware 枚举
    py::enum_<PhaseRole>(m, "PhaseRole")
        .value("RESIDENT_MIGRATABLE", PhaseRole::RESIDENT_MIGRATABLE)
        .value("BURST_GPU_PINNED", PhaseRole::BURST_GPU_PINNED)
        .value("BURST_GPU_PREFERRED", PhaseRole::BURST_GPU_PREFERRED)
        .value("BURST_CPU_LIGHT", PhaseRole::BURST_CPU_LIGHT)
        .export_values();

    py::enum_<DeviceAffinity>(m, "DeviceAffinity")
        .value("GPU_REQUIRED", DeviceAffinity::GPU_REQUIRED)
        .value("GPU_PREFERRED", DeviceAffinity::GPU_PREFERRED)
        .value("CPU_ONLY", DeviceAffinity::CPU_ONLY)
        .value("CPU_PREFERRED", DeviceAffinity::CPU_PREFERRED)
        .export_values();

    py::enum_<LLMServiceLevel>(m, "LLMServiceLevel")
        .value("GPU_NORMAL", LLMServiceLevel::GPU_NORMAL)
        .value("CPU_DEGRADED", LLMServiceLevel::CPU_DEGRADED)
        .value("RESTORING", LLMServiceLevel::RESTORING)
        .export_values();

    py::enum_<MigrationPolicy>(m, "MigrationPolicy")
        .value("ALWAYS_MIGRATE", MigrationPolicy::ALWAYS_MIGRATE)
        .value("COST_AWARE", MigrationPolicy::COST_AWARE)
        .export_values();

    py::enum_<SchedulerPolicy>(m, "SchedulerPolicy")
        .value("SEQUENTIAL", SchedulerPolicy::SEQUENTIAL)
        .value("V1_DUAL_ROLE", SchedulerPolicy::V1_DUAL_ROLE)
        .value("V2_PHASE_AWARE", SchedulerPolicy::V2_PHASE_AWARE)
        .export_values();

    py::enum_<LeaseType>(m, "LeaseType")
        .value("RESIDENT", LeaseType::RESIDENT)
        .value("BURST", LeaseType::BURST)
        .value("SHARED", LeaseType::SHARED)
        .export_values();

    // PhaseAttributes
    py::class_<PhaseAttributes>(m, "PhaseAttributes")
        .def(py::init<>())
        .def_readwrite("role", &PhaseAttributes::role)
        .def_readwrite("device_affinity", &PhaseAttributes::device_affinity)
        .def_readwrite("preemptible", &PhaseAttributes::preemptible)
        .def_readwrite("queueable", &PhaseAttributes::queueable)
        .def_readwrite("migratable", &PhaseAttributes::migratable)
        .def_readwrite("vram_usage_mb", &PhaseAttributes::vram_usage_mb)
        .def_readwrite("typical_duration_s", &PhaseAttributes::typical_duration_s)
        .def_readwrite("is_downstream", &PhaseAttributes::is_downstream)
        .def_readwrite("is_upstream", &PhaseAttributes::is_upstream)
        .def_readwrite("can_overlap_with_gpu", &PhaseAttributes::can_overlap_with_gpu)
        .def("needs_gpu", &PhaseAttributes::needsGpu)
        .def("is_cpu_affine", &PhaseAttributes::isCpuAffine);

    // MigrationCost
    py::class_<MigrationCost>(m, "MigrationCost")
        .def(py::init<>())
        .def_readwrite("kv_cache_save_ms", &MigrationCost::kv_cache_save_ms)
        .def_readwrite("vram_release_ms", &MigrationCost::vram_release_ms)
        .def_readwrite("cpu_load_ms", &MigrationCost::cpu_load_ms)
        .def_readwrite("restore_ms", &MigrationCost::restore_ms)
        .def_readwrite("service_gap_ms", &MigrationCost::service_gap_ms)
        .def("total_downlink_ms", &MigrationCost::totalDownlinkMs)
        .def("total_round_trip_ms", &MigrationCost::totalRoundTripMs);

    // MigrationDecision
    py::class_<MigrationDecision>(m, "MigrationDecision")
        .def(py::init<>())
        .def_readwrite("should_migrate", &MigrationDecision::should_migrate)
        .def_readwrite("reason", &MigrationDecision::reason)
        .def_readwrite("predicted_burst_duration_s", &MigrationDecision::predicted_burst_duration_s)
        .def_readwrite("migration_cost", &MigrationDecision::migration_cost)
        .def_readwrite("wait_cost_s", &MigrationDecision::wait_cost_s)
        .def_readwrite("benefit_s", &MigrationDecision::benefit_s)
        .def_readwrite("strategy", &MigrationDecision::strategy);

    // GPULease
    py::class_<GPULease>(m, "GPULease")
        .def(py::init<>())
        .def_readwrite("holder", &GPULease::holder)
        .def_readwrite("holder_role", &GPULease::holder_role)
        .def_readwrite("lease_type", &GPULease::lease_type)
        .def_readwrite("preemptible", &GPULease::preemptible)
        .def_readwrite("duration_pred_s", &GPULease::duration_pred_s)
        .def_readwrite("vram_required_mb", &GPULease::vram_required_mb);

    // PhaseAwareConfig
    py::class_<PhaseAwareConfig>(m, "PhaseAwareConfig")
        .def(py::init<>())
        .def_readwrite("policy", &PhaseAwareConfig::policy)
        .def_readwrite("migration_policy", &PhaseAwareConfig::migration_policy)
        .def_readwrite("vram_total_mb", &PhaseAwareConfig::vram_total_mb)
        .def_readwrite("max_concurrent_cpu", &PhaseAwareConfig::max_concurrent_cpu)
        .def_readwrite("migration_cost", &PhaseAwareConfig::migration_cost)
        .def_readwrite("short_burst_threshold_s", &PhaseAwareConfig::short_burst_threshold_s)
        .def_readwrite("benefit_threshold_s", &PhaseAwareConfig::benefit_threshold_s)
        .def_readwrite("queue_pressure_threshold", &PhaseAwareConfig::queue_pressure_threshold);

    // LLMState
    py::class_<LLMState>(m, "LLMState")
        .def(py::init<>())
        .def("level", &LLMState::level)
        .def("current_device", &LLMState::currentDevice)
        .def("migration_count", &LLMState::migrationCount)
        .def("total_degraded_time_s", &LLMState::totalDegradedTimeS)
        .def("enter_degraded", &LLMState::enterDegraded)
        .def("enter_restoring", &LLMState::enterRestoring)
        .def("enter_normal", &LLMState::enterNormal);

    // GPULeaseManager
    py::class_<GPULeaseManager>(m, "GPULeaseManager")
        .def(py::init<size_t>(), py::arg("vramTotalMb") = 8192)
        .def("can_acquire", &GPULeaseManager::canAcquire)
        .def("acquire", &GPULeaseManager::acquire)
        .def("release", &GPULeaseManager::release)
        .def("vram_total_mb", &GPULeaseManager::vramTotalMb)
        .def("vram_used_mb", &GPULeaseManager::vramUsedMb)
        .def("vram_available_mb", &GPULeaseManager::vramAvailableMb);

    // IPhaseAwareStrategy
    py::class_<IPhaseAwareStrategy, std::shared_ptr<IPhaseAwareStrategy>>(m, "IPhaseAwareStrategy");

    // DefaultPhaseAwareStrategy
    py::class_<DefaultPhaseAwareStrategy, IPhaseAwareStrategy, std::shared_ptr<DefaultPhaseAwareStrategy>>(m, "DefaultPhaseAwareStrategy")
        .def(py::init<const PhaseAwareConfig&>(), py::arg("config") = PhaseAwareConfig())
        .def("route_task", &DefaultPhaseAwareStrategy::routeTask)
        .def("select_worker_for_phase", &DefaultPhaseAwareStrategy::selectWorkerForPhase)
        .def("should_migrate_llm", &DefaultPhaseAwareStrategy::shouldMigrateLLM)
        .def("get_llm_state", &DefaultPhaseAwareStrategy::getLLMState, py::return_value_policy::reference_internal)
        .def("get_lease_manager", &DefaultPhaseAwareStrategy::getLeaseManager, py::return_value_policy::reference_internal)
        .def("migrate_llm_to_cpu", &DefaultPhaseAwareStrategy::migrateLLMToCPU, py::arg("urgent") = false)
        .def("restore_llm_to_gpu", &DefaultPhaseAwareStrategy::restoreLLMToGPU)
        .def("set_migration_callbacks", &DefaultPhaseAwareStrategy::setMigrationCallbacks);

    // getPhasePreset
    m.def("get_phase_preset", &getPhasePreset, py::arg("phase_name"));

}
