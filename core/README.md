# Core Module Documentation

This directory contains the core logic of the Xiaoyou system, reorganized into a clean three-layer architecture.

## Architecture Overview

The system is divided into four main layers:

1. **Core Engine Layer (`core_engine/`)**:
   - Manages system lifecycle, configuration, events, and models.
   - Key components: `CoreEngine`, `EventBus`, `LifecycleManager`, `ConfigManager`, `ModelManager`.

2. **Service Layer (`services/`)**:
   - Implements high-level business logic and orchestrates modules.
   - Key components: `AvelineService` (Main Character Logic), `ActiveCareService`, `TaskScheduler`, `MonitoringSystem`.

3. **Module Layer (`modules/`)**:
   - Encapsulates specific capabilities and model interactions.
   - Key components: `LLMModule`, `ImageModule`, `VisionModule`, `VoiceModule`, `MemoryModule`.

4. **Interface Layer (`interfaces/`)**:
   - Handles external communication via HTTP and WebSocket.

## Directory Structure

- `core_engine/`: Core infrastructure components.
- `services/`: Business services.
  - `aveline/`: Character personality and interaction logic.
  - `active_care/`: Proactive engagement logic.
  - `scheduler/`: Task scheduling and execution.
  - `monitoring/`: System resource monitoring.
- `modules/`: Functional capabilities.
  - `llm/`: Large Language Model integration.
  - `image/`: Image generation (Stable Diffusion).
  - `vision/`: Visual understanding (VLM).
  - `voice/`: TTS and STT capabilities.
  - `memory/`: Long-term memory and context management.
- `interfaces/`: API adapters.
- `utils/`: Shared utility functions.

## Key Changes in Refactoring

- **Modularization**: `ModelAdapter` has been deprecated and split into dedicated `LLMModule`, `ImageModule`, and `VisionModule`.
- **Memory Management**: `MemoryModule` is now a dedicated component in the module layer.
- **Service Organization**: Services are grouped by domain rather than being flat files.
- **Dependency Management**: Dependencies are now cleaner, with Services depending on Modules, and Core Engine managing the infrastructure.
