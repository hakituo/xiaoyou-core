# ADR-001: Architecture Refactoring for MVP Core

## Status
Accepted

## Context
The project `xiaoyou-core` has grown organically, resulting in mixed concerns, tight coupling between business logic and infrastructure (LLM, Frameworks), and scattered configuration. This makes testing, maintenance, and scalability difficult.

## Decision
We decided to refactor `mvp_core` into a clean Clean Architecture / Hexagonal Architecture style with strict layering:

1.  **Presentation Layer (`presentation/`)**: Handles HTTP/WebSocket interfaces. Depends only on Domain.
2.  **Domain Layer (`domain/`)**: Contains pure business logic (Entities, Services, Events). Defines Interfaces (Ports) for infrastructure. **Depends on nothing.**
3.  **Data Layer (`data/`)**: Implements Domain Interfaces (Adapters). Depends on Domain and external libraries (Transformers, DB drivers).
4.  **Shared Kernel (`shared/`)**: Utilities and DI container.

## Consequences

### Positive
*   **Testability**: Domain logic can be tested in isolation using Mock Adapters.
*   **Flexibility**: Switching LLM providers or Databases only requires a new Adapter in `data/`, without touching Domain logic.
*   **Maintainability**: Clear boundaries make it easier for new developers to understand where code belongs.

### Negative
*   **Boilerplate**: Requires defining Interfaces and DTOs, which adds initial development overhead.
*   **Complexity**: Dependency Injection requires a container setup.

## Technical Implementation
*   **Dependency Injection**: A simple `Container` class in `shared/di.py` manages singleton and factory registrations.
*   **Async First**: All I/O bound interfaces are `async`.
*   **Pydantic**: Used for Domain Entities to ensure type safety and validation.
