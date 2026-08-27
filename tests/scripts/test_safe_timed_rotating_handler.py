"""验证 SafeTimedRotatingFileHandler 在文件被占用时轮转不崩溃

场景：模拟 Windows 下日志文件被其他句柄占用，TimedRotatingFileHandler.doRollover()
会因 os.rename 失败抛 PermissionError。SafeTimedRotatingFileHandler 应吞掉异常并
重新打开当前文件继续写入。
"""

import logging
import os
import shutil
import sys
import tempfile

sys.path.insert(0, r"D:\AI\xiaoyou-core")

from clients.bots.qq_official.transport import SafeTimedRotatingFileHandler


def main():
    d = tempfile.mkdtemp()
    f = os.path.join(d, "test.log")
    try:
        h = SafeTimedRotatingFileHandler(
            f, when="S", backupCount=3, encoding="utf-8"
        )
        h.setLevel(logging.DEBUG)
        h.setFormatter(logging.Formatter("%(message)s"))

        lg = logging.getLogger("test_safe_rotating")
        lg.handlers.clear()
        lg.addHandler(h)
        lg.setLevel(logging.DEBUG)

        lg.info("first line")
        h.flush()

        # 模拟另一个句柄占用该文件
        holder = open(f, "a", encoding="utf-8")
        try:
            # 普通 TimedRotatingFileHandler 在这里会抛 PermissionError
            h.doRollover()
            print("doRollover OK (no exception)")

            lg.info("second line after rollover")
            h.flush()
            print("still writable after rollover")

            # 确认日志内容确实写进去了
            with open(f, "r", encoding="utf-8") as reader:
                content = reader.read()
            assert "second line after rollover" in content, (
                f"日志内容未写入: {content!r}"
            )
            print("content verified:", repr(content))
        finally:
            holder.close()
        print("PASS")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main()
