#include "worker_base.h"

namespace ai_scheduler {

WorkerBase::WorkerBase(const std::string& name)
    : name_(name), initialized_(false) {
}

} // namespace ai_scheduler