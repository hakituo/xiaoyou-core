@echo off
cls

REM 使用完整Java路径运行mirai-console
"C:\Program Files\Java\jdk-17\bin\java.exe" -jar mcl.jar

REM 等待mirai-console完全启动
ping 127.0.0.1 -n 10 > nul

echo 正在启动QQ机器人...
python qq_bot.py

pause