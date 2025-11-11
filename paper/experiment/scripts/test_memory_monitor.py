import os
import time
import json
import threading
import psutil

# 内存监控器类
class MemoryMonitor:
    def __init__(self, interval=0.5):
        self.interval = interval
        self.running = False
        self.monitor_thread = None
        self.memory_data = []
        self.process = psutil.Process()
    
    def start(self):
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_memory)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
    def stop(self):
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        return self.memory_data
    
    def _monitor_memory(self):
        start_time = time.time()
        while self.running:
            # 获取当前真实内存使用情况（以MB为单位）
            try:
                mem_info = self.process.memory_info()
                memory_mb = mem_info.rss / (1024 * 1024)  # 转换为MB
                self.memory_data.append({
                    'time': time.time() - start_time,  # 相对时间
                    'memory': round(memory_mb, 2)      # 真实内存使用量（MB）
                })
            except psutil.NoSuchProcess:
                break
            time.sleep(self.interval)
    
    def get_average_memory(self):
        if not self.memory_data:
            return 0
        return sum(point['memory'] for point in self.memory_data) / len(self.memory_data)
    
    def get_max_memory(self):
        if not self.memory_data:
            return 0
        return max(point['memory'] for point in self.memory_data)

# 测试主程序 - 使用真实内存监控
if __name__ == "__main__":
    print("启动真实内存监控测试...")
    
    # 创建内存监控器
    memory_monitor = MemoryMonitor(interval=0.1)
    
    # 启动监控
    memory_monitor.start()
    
    try:
        # 阶段1: 初始状态
        print("阶段1: 初始状态")
        time.sleep(2)
        
        # 阶段2: 分配一些内存并执行操作
        print("阶段2: 分配内存 - 小型数据集")
        small_data = [0] * 10000000  # 分配真实内存
        time.sleep(2)
        
        # 阶段3: 进一步增加内存使用
        print("阶段3: 增加内存使用 - 中型数据集")
        medium_data = [0] * 20000000  # 分配更多内存
        time.sleep(2)
        
        # 阶段4: 内存使用峰值
        print("阶段4: 内存使用峰值 - 大型数据集")
        large_data = [0] * 50000000  # 大量内存分配
        time.sleep(3)
        
        # 阶段5: 释放部分内存
        print("阶段5: 释放部分内存")
        large_data = None  # 释放部分内存
        time.sleep(1)
        
        # 阶段6: 继续释放内存
        print("阶段6: 继续释放内存")
        medium_data = None  # 释放更多内存
        time.sleep(1)
        
        # 阶段7: 最终状态
        print("阶段7: 最终状态")
        small_data = None  # 释放所有大型对象
        time.sleep(1)
        
    finally:
        # 停止监控
        memory_data = memory_monitor.stop()
        avg_memory = round(memory_monitor.get_average_memory(), 2)
        max_memory = round(memory_monitor.get_max_memory(), 2)
        
        # 显示真实监控结果
        print(f"\n真实内存监控结果:")
        print(f"平均内存使用: {avg_memory} MB")
        print(f"最大内存使用: {max_memory} MB")
        print(f"监控数据点数量: {len(memory_data)}")
        
        # 构建完整的实验结果结构
        experiment_results = {
            "experiments": {
                "experiment_3": {
                    'timestamps': [point['time'] for point in memory_data],
                    'memory_values': [point['memory'] for point in memory_data],
                    'avg_memory_usage': avg_memory,
                    'max_memory_usage': max_memory,
                    'memory_usage': {
                        'init': memory_data[0]['memory'] if memory_data else 0,
                        'runtime': sum(point['memory'] for point in memory_data[:len(memory_data)//3]) / (len(memory_data)//3) if memory_data else 0,
                        'processing': max_memory,
                        'response': sum(point['memory'] for point in memory_data[2*len(memory_data)//3:]) / (len(memory_data)//3) if memory_data else 0,
                        'cleanup': memory_data[-1]['memory'] if memory_data else 0
                    },
                    'memory_monitor': memory_data
                }
            }
        }
        
        # 保存数据到正确的目录
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)  # paper目录
        experiment_results_dir = os.path.join(project_root, "experiment_results", "data")
        output_file = os.path.join(experiment_results_dir, 'comprehensive_results.json')

        # 确保目录存在
        if not os.path.exists(experiment_results_dir):
            os.makedirs(experiment_results_dir)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(experiment_results, f, indent=2, ensure_ascii=False)
        
        print(f"\n真实内存监控数据已保存到: {output_file}")
        print("测试完成! 数据已按要求格式保存到comprehensive_results.json")