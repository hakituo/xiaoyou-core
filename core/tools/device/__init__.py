"""设备控制工具集

这些工具的执行层在手机前端 Android, 后端只负责:
- 定义工具 schema (暴露给 LLM)
- 通过 DeviceCommandBridge 下发指令到手机端
- 接收手机端结果回传给 LLM

工具分类: device (默认仅 Master 可用)
"""
