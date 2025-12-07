#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
System Memory Management Service
Provides system memory monitoring, management, and garbage collection.
"""

import gc
import logging
import threading
import time
import psutil
from typing import Dict, Any, Optional

from config.integrated_config import get_settings

logger = logging.getLogger(__name__)


class MemoryMonitor:
    """Memory monitor for system and process memory usage"""
    
    def __init__(self, interval: float = 5.0):
        """Initialize memory monitor
        
        Args:
            interval: Monitoring interval (seconds)
        """
        self.interval = interval
        self.process = psutil.Process()
        self.running = False
        self.monitor_thread = None
        logger.info("Memory monitor initialized")
    
    def start(self):
        """Start memory monitoring"""
        if self.running:
            logger.warning("Memory monitor already running")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Memory monitor started")
    
    def stop(self):
        """Stop memory monitoring"""
        if not self.running:
            logger.warning("Memory monitor not running")
            return
        
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.0)
        logger.info("Memory monitor stopped")
    
    def _monitor_loop(self):
        """Monitoring loop"""
        while self.running:
            try:
                memory_info = self.get_memory_info()
                # logger.debug(f"Memory usage: {memory_info}")
                # Threshold checks can be added here
            except Exception as e:
                logger.error(f"Memory monitoring error: {e}")
            time.sleep(self.interval)
    
    def get_memory_info(self) -> Dict[str, Any]:
        """Get current memory usage info
        
        Returns:
            Dictionary containing memory usage info
        """
        process_memory = self.process.memory_info()
        system_memory = psutil.virtual_memory()
        
        return {
            "process_rss_mb": process_memory.rss / (1024 * 1024),  # Process physical memory (MB)
            "process_vms_mb": process_memory.vms / (1024 * 1024),  # Process virtual memory (MB)
            "system_total_mb": system_memory.total / (1024 * 1024),  # System total memory (MB)
            "system_available_mb": system_memory.available / (1024 * 1024),  # System available memory (MB)
            "system_used_percent": system_memory.percent,  # System memory usage percentage
        }
    
    def get_memory_usage(self) -> Dict[str, float]:
        """Get memory usage summary
        
        Returns:
            Dictionary containing process and system memory usage
        """
        memory_info = self.get_memory_info()
        return {
            "process_usage_mb": memory_info["process_rss_mb"],
            "system_usage_percent": memory_info["system_used_percent"]
        }


class GarbageCollector:
    """Custom Garbage Collector, enhancing Python's default GC"""
    
    def __init__(self, auto_collect_interval: float = 60.0, threshold: float = 0.8):
        """Initialize Garbage Collector
        
        Args:
            auto_collect_interval: Auto collection interval (seconds)
            threshold: Memory usage threshold to trigger collection (0.0-1.0)
        """
        self.auto_collect_interval = auto_collect_interval
        self.threshold = threshold
        self.running = False
        self.gc_thread = None
        self.stats = {
            "collect_count": 0,
            "last_collect_time": 0,
            "objects_collected": 0
        }
        logger.info("Garbage collector initialized")
    
    def start(self):
        """Start automatic garbage collection"""
        if self.running:
            logger.warning("Garbage collector already running")
            return
        
        self.running = True
        self.gc_thread = threading.Thread(target=self._gc_loop, daemon=True)
        self.gc_thread.start()
        logger.info("Automatic garbage collection started")
    
    def stop(self):
        """Stop automatic garbage collection"""
        if not self.running:
            logger.warning("Garbage collector not running")
            return
        
        self.running = False
        if self.gc_thread:
            self.gc_thread.join(timeout=1.0)
        logger.info("Automatic garbage collection stopped")
    
    def collect(self):
        """Execute garbage collection immediately
        
        Returns:
            Number of objects collected
        """
        logger.info("Executing garbage collection")
        before_count = len(gc.get_objects())
        
        # Execute full garbage collection
        count0 = gc.collect(0)
        count1 = gc.collect(1)
        count2 = gc.collect(2)
        
        after_count = len(gc.get_objects())
        objects_collected = before_count - after_count
        
        self.stats["collect_count"] += 1
        self.stats["last_collect_time"] = time.time()
        self.stats["objects_collected"] += objects_collected
        
        logger.info(f"Garbage collection complete: Gen0({count0}), Gen1({count1}), Gen2({count2}), Total collected({objects_collected})")
        return objects_collected
    
    def _gc_loop(self):
        """Garbage collection loop"""
        while self.running:
            try:
                # Check memory usage, trigger collection if threshold exceeded
                memory_percent = psutil.virtual_memory().percent / 100
                if memory_percent > self.threshold:
                    logger.warning(f"Memory usage exceeded threshold ({memory_percent:.2%}), triggering GC")
                    self.collect()
            except Exception as e:
                logger.error(f"Garbage collection loop error: {e}")
            time.sleep(self.auto_collect_interval)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get GC statistics
        
        Returns:
            Statistics dictionary
        """
        return dict(self.stats)


class SystemMemoryManager:
    """System Memory Manager, responsible for managing and optimizing application memory usage"""
    
    def __init__(self):
        """Initialize System Memory Manager"""
        settings = get_settings()
        
        # Monitor interval defaults to 5.0s, could be configurable if needed
        self.monitor = MemoryMonitor(interval=5.0)
        
        # Use config settings for GC
        # Convert threshold from percentage (0-100) to float (0.0-1.0)
        gc_threshold = settings.memory.very_high_memory_threshold / 100.0
        
        self.gc = GarbageCollector(
            auto_collect_interval=float(settings.memory.gc_interval),
            threshold=gc_threshold
        )
        self.resource_tracker = {}
        self.lock = threading.RLock()
        logger.info("System Memory Manager initialized")
    
    def start(self):
        """Start memory management service"""
        self.monitor.start()
        self.gc.start()
        logger.info("Memory management service started")
    
    def stop(self):
        """Stop memory management service"""
        self.gc.stop()
        self.monitor.stop()
        logger.info("Memory management service stopped")
    
    def track_resource(self, resource_id: str, resource: Any, size_estimate: Optional[int] = None):
        """Track resource usage
        
        Args:
            resource_id: Resource identifier
            resource: Resource object to track
            size_estimate: Estimated size of resource (bytes)
        """
        with self.lock:
            self.resource_tracker[resource_id] = {
                "resource": resource,
                "size_estimate": size_estimate,
                "timestamp": time.time()
            }
            logger.debug(f"Resource tracked: {resource_id}")
    
    def untrack_resource(self, resource_id: str):
        """Untrack resource
        
        Args:
            resource_id: Resource identifier
        """
        with self.lock:
            if resource_id in self.resource_tracker:
                del self.resource_tracker[resource_id]
                logger.debug(f"Resource untracked: {resource_id}")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics
        
        Returns:
            Memory statistics dictionary
        """
        with self.lock:
            return {
                "monitor_info": self.monitor.get_memory_info(),
                "tracked_resources": len(self.resource_tracker),
                "gc_stats": self.gc.get_stats()
            }
    
    def optimize_memory(self):
        """Execute memory optimization"""
        logger.info("Executing memory optimization")
        # Execute garbage collection
        self.gc.collect()


# Global System Memory Manager Instance
_system_memory_manager: Optional[SystemMemoryManager] = None


def initialize_system_memory_manager() -> SystemMemoryManager:
    """Initialize global System Memory Manager
    
    Returns:
        SystemMemoryManager instance
    """
    global _system_memory_manager
    
    if _system_memory_manager is None:
        _system_memory_manager = SystemMemoryManager()
        _system_memory_manager.start()
        logger.info("Global System Memory Manager initialized")
    
    return _system_memory_manager


def get_system_memory_manager() -> Optional[SystemMemoryManager]:
    """Get global System Memory Manager instance
    
    Returns:
        SystemMemoryManager instance, or None if not initialized
    """
    global _system_memory_manager
    
    if _system_memory_manager is None:
        logger.warning("System Memory Manager not initialized")
        return initialize_system_memory_manager()
    
    return _system_memory_manager

async def shutdown_system_memory_manager():
    """Shutdown global System Memory Manager"""
    global _system_memory_manager
    if _system_memory_manager:
        _system_memory_manager.stop()
        _system_memory_manager = None
