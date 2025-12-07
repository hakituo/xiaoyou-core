from typing import Dict, Type, Any, Optional

class Container:
    _instances: Dict[Type, Any] = {}
    _factories: Dict[Type, Any] = {}

    @classmethod
    def register(cls, interface: Type, implementation: Any):
        """Register a singleton instance"""
        cls._instances[interface] = implementation

    @classmethod
    def register_factory(cls, interface: Type, factory_func):
        """Register a factory function"""
        cls._factories[interface] = factory_func

    @classmethod
    def resolve(cls, interface: Type) -> Any:
        if interface in cls._instances:
            return cls._instances[interface]
        
        if interface in cls._factories:
            return cls._factories[interface]()
            
        raise ValueError(f"No implementation registered for {interface}")

# Global container instance
container = Container()
