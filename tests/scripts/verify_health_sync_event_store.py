# -*- coding: utf-8 -*-
"""验证健康数据事件流存储改造是否成功。

覆盖点:
1. latest.json 单文件覆盖,不再每次同步生成新文件
2. 高频通道上报的 None 字段不覆盖 latest 已有值
3. 心率异常/显著波动才产生事件,微小波动不刷屏
4. 饮水/进食按增量追加,不是覆盖
5. sleep_end_time 变化产生 wake_up 事件
6. 步数按里程碑记录
7. query_health_data 工具能读到数据

用法: venv_core/Scripts/python.exe tests/scripts/verify_health_sync_event_store.py
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PASSED = []
FAILED = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name} :: {detail}")


def main() -> int:
    # 用临时目录隔离,不污染真实 companion_data
    tmp = Path(tempfile.mkdtemp(prefix="health_sync_verify_"))
    import core.utils.data_paths as dp
    dp.get_companion_data_dir = lambda: tmp  # type: ignore[assignment]

    import core.services.health_sync.store as store
    store.get_companion_data_dir = lambda: tmp  # type: ignore[assignment]

    try:
        print("\n=== 1. 首次同步(全量) ===")
        r1 = store.ingest_snapshot({
            "source": "samsung_health",
            "heart_rate": 72,
            "steps_today": 500,
            "weight_kg": 60.0,
            "water_intake_ml": 0.0,
            "nutrition_calories": 0.0,
            "sleep_end_time": "2026-08-07T07:00:00",
            "sleep_start_time": "2026-08-06T23:30:00",
            "sleep_minutes": 450,
        })
        types1 = [e["type"] for e in r1.events]
        check("首次同步产生 wake_up 事件", "wake_up" in types1, str(types1))
        check("首次同步产生 heart_rate 事件", "heart_rate" in types1, str(types1))
        check("wake_up 结果被正确捕获", r1.wake_up is not None)

        print("\n=== 2. 高频通道(只带心率, 微小波动) ===")
        r2 = store.ingest_snapshot({"heart_rate": 74})
        types2 = [e["type"] for e in r2.events]
        check("心率微小波动(72->74)不产生事件", "heart_rate" not in types2, str(types2))

        latest = store.read_latest()
        check("高频同步未抹掉体重", latest.get("weight_kg") == 60.0, str(latest.get("weight_kg")))
        check("高频同步未抹掉睡眠", latest.get("sleep_minutes") == 450)
        check("心率已更新为最新值", latest.get("heart_rate") == 74)

        print("\n=== 3. 心率显著波动 / 异常 ===")
        r3 = store.ingest_snapshot({"heart_rate": 130})
        hr_ev = [e for e in r3.events if e["type"] == "heart_rate"]
        check("心率飙到130产生事件", len(hr_ev) == 1, str(r3.events))
        check("心率130被标记异常", hr_ev and hr_ev[0].get("abnormal") is True)
        check("心率异常等级为偏高", hr_ev and hr_ev[0].get("level") == "偏高")

        print("\n=== 4. 饮水按增量追加 ===")
        store.ingest_snapshot({"water_intake_ml": 250.0})
        r5 = store.ingest_snapshot({"water_intake_ml": 700.0})
        w_ev = [e for e in r5.events if e["type"] == "water"]
        check("第二次饮水产生事件", len(w_ev) == 1, str(r5.events))
        check("饮水记录的是增量450而非总量", w_ev and w_ev[0].get("delta_ml") == 450.0,
              str(w_ev))
        check("饮水同时记录累计700", w_ev and w_ev[0].get("total_ml") == 700.0)

        print("\n=== 5. 进食按增量追加 ===")
        r6 = store.ingest_snapshot({
            "nutrition_calories": 620.0,
            "nutrition_protein": 30.0,
        })
        m_ev = [e for e in r6.events if e["type"] == "meal"]
        check("进食产生 meal 事件", len(m_ev) == 1, str(r6.events))
        check("进食记录增量热量620", m_ev and m_ev[0].get("delta_kcal") == 620.0)

        print("\n=== 6. 步数里程碑 ===")
        r7 = store.ingest_snapshot({"steps_today": 900})
        check("步数500->900未跨千不记录",
              "steps" not in [e["type"] for e in r7.events], str(r7.events))
        r8 = store.ingest_snapshot({"steps_today": 1200})
        s_ev = [e for e in r8.events if e["type"] == "steps"]
        check("步数跨过1000产生里程碑事件", len(s_ev) == 1, str(r8.events))
        check("里程碑值为1000", s_ev and s_ev[0].get("milestone") == 1000)

        print("\n=== 7. 起床事件不重复 ===")
        r9 = store.ingest_snapshot({"sleep_end_time": "2026-08-07T07:00:00"})
        check("相同 sleep_end_time 不重复产生 wake_up",
              "wake_up" not in [e["type"] for e in r9.events], str(r9.events))
        r10 = store.ingest_snapshot({"sleep_end_time": "2026-08-08T06:40:00"})
        check("新的 sleep_end_time 产生 wake_up",
              "wake_up" in [e["type"] for e in r10.events], str(r10.events))

        print("\n=== 8. 文件结构 ===")
        base = tmp / "health_sync"
        top_files = [p.name for p in base.iterdir() if p.is_file()]
        check("顶层文件含 latest.json", "latest.json" in top_files, str(top_files))
        ev_files = list((base / "events").glob("*.jsonl"))
        check("事件流按天一个 jsonl", len(ev_files) == 1, str([p.name for p in ev_files]))

        lines = ev_files[0].read_text(encoding="utf-8").strip().split("\n")
        check("事件流是追加而非覆盖(多条记录)", len(lines) >= 8, f"实际 {len(lines)} 条")
        check("每行都是合法 JSON",
              all(json.loads(ln).get("ts") for ln in lines))

        print("\n=== 9. 读取接口 ===")
        all_ev = store.read_events(limit=500)
        check("read_events 能读回全部事件", len(all_ev) == len(lines))
        hr_only = store.read_events(limit=500, types=["heart_rate"])
        check("read_events 类型过滤生效",
              all(e["type"] == "heart_rate" for e in hr_only) and len(hr_only) >= 2,
              str(len(hr_only)))

        print("\n=== 10. AI 工具查询 ===")
        from core.tools.health_data_tool import HealthDataTool
        tool = HealthDataTool()
        now_out = json.loads(asyncio.run(tool._run(mode="now")))
        check("工具 now 模式返回心率", "心率(bpm)" in now_out, str(list(now_out)[:5]))
        check("工具 now 模式返回体重", "体重(kg)" in now_out)
        tl_out = json.loads(asyncio.run(tool._run(mode="timeline", types="water")))
        check("工具 timeline 模式能过滤饮水",
              tl_out.get("count", 0) >= 1
              and all(e["type"] == "water" for e in tl_out.get("events", [])),
              str(tl_out))

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 50)
    print(f"通过 {len(PASSED)} 项, 失败 {len(FAILED)} 项")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        return 1
    print("健康数据事件流改造验证通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
