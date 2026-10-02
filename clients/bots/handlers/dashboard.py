import asyncio
import json
import os
import platform
import time

from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.settings import (
    _HAS_STATUS_RENDERER,
    generate_dashboard_detail_image,
    generate_dashboard_overview_image,
)
from clients.bots.qq.utils import _build_cq_image, _truncate_text

class DashboardHandler(BaseHandler):
    async def show_status(self, session_id, prefs, is_master, rest: str = ""):
        section = str(rest or "").strip()
        if not section:
            await self._show_dashboard_overview(session_id, prefs, is_master)
            return
        parts = section.split(None, 1)
        key = str(parts[0] or "").strip().lower()
        aliases = {
            "总览": "overview",
            "概览": "overview",
            "overview": "overview",
            "资源": "resources",
            "res": "resources",
            "resources": "resources",
            "服务": "services",
            "svc": "services",
            "services": "services",
            "模块": "modules",
            "module": "modules",
            "modules": "modules",
            "记忆": "memory",
            "memory": "memory",
            "会话": "sessions",
            "session": "sessions",
            "sessions": "sessions",
            "日程": "workspace",
            "提醒": "workspace",
            "workspace": "workspace",
            "用户": "user",
            "user": "user",
            "生物": "bio",
            "生命": "bio",
            "life": "bio",
            "bio": "bio",
            "biological": "bio",
            "情绪": "emotion",
            "emo": "emotion",
            "emotion": "emotion",
        }
        section_key = aliases.get(key)
        if not section_key or section_key == "overview":
            await self._show_dashboard_overview(session_id, prefs, is_master)
            return
        await self._show_dashboard_detail(session_id, prefs, is_master, section_key)

    async def fetch_dashboard_data(self, session_id: str, prefs: dict):
        tasks = [
            self.api_request("GET", "/health"),
            self.api_request("GET", "/api/v1/system/resources"),
            self.api_request("GET", "/api/v1/system/stats"),
            self.api_request("GET", "/api/v1/memories/stats", params={"user_id": "default"}),
            self.api_request("GET", "/api/v1/sessions?include_external=true"),
            self.api_request("GET", "/api/v1/user/status"),
            self.api_request("GET", "/api/v1/diary/scheduled"),
            self.api_request("GET", "/api/v1/tutor/notifications", params={"user_id": "default"}),
            self.api_request("GET", "/api/v1/life/status"),
            self.api_request("GET", "/api/v1/vision/image/models"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        def _unpack(idx: int):
            r = results[idx]
            if isinstance(r, Exception):
                return 0, {"error": str(r)}
            if isinstance(r, (list, tuple)) and len(r) == 2:
                return r
            return 0, {"error": "invalid_response"}

        health_s, health_d = _unpack(0)
        res_s, res_d = _unpack(1)
        stats_s, stats_d = _unpack(2)
        mem_s, mem_d = _unpack(3)
        sess_s, sess_d = _unpack(4)
        user_s, user_d = _unpack(5)
        sch_s, sch_d = _unpack(6)
        notif_s, notif_d = _unpack(7)
        life_s, life_d = _unpack(8)
        imgm_s, imgm_d = _unpack(9)

        # Access adapter session emotions if available
        emotion_data = self.adapter._session_emotions.get(session_id) if hasattr(self.adapter, "_session_emotions") else None

        # 安全处理 image_models 数据
        image_models_data = {}
        if imgm_s == 200 and isinstance(imgm_d, dict):
            image_models_data = imgm_d.get("data") or {}
        elif isinstance(imgm_d, dict) and "data" in imgm_d:
            image_models_data = imgm_d.get("data") or {}

        payload = {
            "health": health_d if health_s == 200 else {},
            "resources": (res_d.get("data") if isinstance(res_d, dict) else {}) if res_s == 200 else {},
            "stats": (stats_d.get("data") if isinstance(stats_d, dict) else {}) if stats_s == 200 else {},
            "memory_stats": (mem_d.get("data") if isinstance(mem_d, dict) else {}) if mem_s == 200 else {},
            "sessions": (sess_d.get("data") if isinstance(sess_d, dict) else []) if sess_s == 200 else [],
            "user_status": (user_d.get("data") if isinstance(user_d, dict) else {}) if user_s == 200 else {},
            "scheduled": sch_d if sch_s == 200 else [],
            "notifications": (notif_d.get("data") if isinstance(notif_d, dict) else []) if notif_s == 200 else [],
            "life_status": (life_d.get("data") if isinstance(life_d, dict) else {}) if life_s == 200 else {},
            "image_models": image_models_data,
            "prefs": prefs or {},
            "emotion": emotion_data,
        }
        return payload

    async def _show_dashboard_overview(self, session_id: str, prefs: dict, is_master: bool):
        try:
            data = await self.fetch_dashboard_data(session_id, prefs)
            health = data.get("health") if isinstance(data.get("health"), dict) else {}
            resources = data.get("resources") if isinstance(data.get("resources"), dict) else {}
            mem_stats = data.get("memory_stats") if isinstance(data.get("memory_stats"), dict) else {}
            user_status = data.get("user_status") if isinstance(data.get("user_status"), dict) else {}
            life_status = data.get("life_status") if isinstance(data.get("life_status"), dict) else {}
            sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []
            image_models_raw = data.get("image_models") if isinstance(data.get("image_models"), dict) else {}

            services = health.get("services") if isinstance(health.get("services"), dict) else {}
            service_count = len(services)
            unhealthy = 0
            active_care_status = "—"
            if service_count:
                for k, v in services.items():
                    st = str((v or {}).get("status") if isinstance(v, dict) else v)
                    if st in {"unhealthy", "error"}:
                        unhealthy += 1
                acs = services.get("active_care_service")
                if isinstance(acs, dict):
                    active_care_status = str(acs.get("status") or "—")
            memory_total = None
            try:
                memory_total = int(mem_stats.get("total_memories"))
            except Exception:
                memory_total = None

            top_categories = []
            counts = mem_stats.get("counts") if isinstance(mem_stats.get("counts"), dict) else {}
            dist = mem_stats.get("distribution") if isinstance(mem_stats.get("distribution"), dict) else {}
            try:
                for cat, cnt in sorted(counts.items(), key=lambda kv: int(kv[1]), reverse=True)[:5]:
                    pct = dist.get(cat)
                    row = {"category": cat, "count": int(cnt)}
                    if isinstance(pct, (int, float)):
                        row["pct"] = float(pct)
                    top_categories.append(row)
            except Exception:
                top_categories = []

            pref_model_name = str(prefs.get("model_name") or "").strip()
            model_info = pref_model_name or (prefs.get("chat_model") or "Default")
            persona_info = prefs.get("persona_filename") or "Unknown"
            if not is_master:
                persona_info = "ENCRYPTED / PUBLIC"

            emotion_data = data.get("emotion")
            emotion_label = "neutral"
            if isinstance(emotion_data, dict) and emotion_data:
                emotion_label = max(emotion_data, key=emotion_data.get)
            elif isinstance(user_status.get("aveline"), dict) and user_status.get("aveline").get("emotion"):
                emotion_label = str(user_status.get("aveline").get("emotion"))

            cpu_usage = health.get("metrics", {}).get("cpu_usage") if isinstance(health.get("metrics"), dict) else None
            mem_usage = health.get("metrics", {}).get("memory_usage") if isinstance(health.get("metrics"), dict) else None
            gpu_usage = health.get("metrics", {}).get("gpu_usage") if isinstance(health.get("metrics"), dict) else None

            if not isinstance(cpu_usage, (int, float)):
                cpu_usage = resources.get("cpu_usage")
            if not isinstance(mem_usage, (int, float)):
                mem_usage = resources.get("memory_usage")
            if not isinstance(gpu_usage, (int, float)):
                gpu_usage = resources.get("gpu_usage")

            session_total = 0
            session_latest = "—"
            try:
                session_total = len(sessions)
                if session_total and isinstance(sessions[0], dict):
                    title = str(sessions[0].get("title") or "—")
                    sid = sessions[0].get("id")
                    sid8 = str(sid)[:8] if sid else "—"
                    session_latest = f"{title} ({sid8})"
            except Exception:
                session_total = 0
                session_latest = "—"

            def _count_image_models(raw):
                if not raw or not isinstance(raw, dict):
                    return 0
                total = 0
                for _, group_data in raw.items():
                    if isinstance(group_data, list):
                        total += len(group_data)
                        continue
                    if not isinstance(group_data, dict):
                        continue
                    for key in ("checkpoints", "models", "loras"):
                        items = group_data.get(key)
                        if isinstance(items, list):
                            total += len(items)
                return total

            img_models_cnt = _count_image_models(image_models_raw)
            image_models_total = resources.get("image_models_total")
            if not isinstance(image_models_total, int) or image_models_total <= 0:
                image_models_total = img_models_cnt if img_models_cnt > 0 else (image_models_total or 0)

            voices_total = resources.get("voices_total")
            if not isinstance(voices_total, int) or voices_total <= 0:
                voices_total = 4 if services.get("tts_service") else (voices_total or 0)

            active_model = resources.get("active_model")
            if not active_model or str(active_model).lower() in {"none", "null", ""}:
                active_model = model_info

            payload = {
                "title": "AVELINE CORE SYSTEM",
                "subtitle": f"QQ PANEL // {platform.system().upper()}",
                "overall_status": health.get("status") or "unknown",
                "cpu_usage": cpu_usage if isinstance(cpu_usage, (int, float)) else 0.0,
                "memory_usage": mem_usage if isinstance(mem_usage, (int, float)) else 0.0,
                "gpu_usage": gpu_usage if isinstance(gpu_usage, (int, float)) else None,
                "models_total": resources.get("models_total"),
                "models_loaded": resources.get("models_loaded"),
                "image_models_total": image_models_total,
                "voices_total": voices_total,
                "active_model": active_model,
                "service_count": service_count,
                "unhealthy_service_count": unhealthy,
                "active_care_status": active_care_status,
                "memory_total": memory_total,
                "memory_top_categories": top_categories,
                "model_name": model_info,
                "persona_name": persona_info,
                "session_total": session_total,
                "session_latest": session_latest,
                "emotion": emotion_label,
                "emotion_scores": emotion_data if isinstance(emotion_data, dict) else None,
                "is_master": is_master,
                "core_metrics": {
                    "energy": (life_status.get("life") or {}).get("energy"),
                    "mood_score": (life_status.get("life") or {}).get("mood_score"),
                    "immune_damage": (life_status.get("life") or {}).get("immune_damage"),
                    "immune_health": (life_status.get("immune") or {}).get("immune_health"),
                    "bionic_health": (life_status.get("life") or {}).get("bionic_health"),
                    "cpu_usage": cpu_usage if isinstance(cpu_usage, (int, float)) else 0.0,
                    "memory_usage": mem_usage if isinstance(mem_usage, (int, float)) else 0.0,
                    "gpu_usage": gpu_usage if isinstance(gpu_usage, (int, float)) else None,
                    "service_count": service_count,
                    "unhealthy_service_count": unhealthy,
                },
                "commands": [
                    "/状态 资源",
                    "/状态 服务",
                    "/状态 模块",
                    "/状态 记忆",
                    "/状态 会话",
                    "/状态 日程",
                    "/状态 生物",
                    "/状态 情绪",
                ],
            }

            if _HAS_STATUS_RENDERER and callable(generate_dashboard_overview_image):
                img_path = generate_dashboard_overview_image(payload)
                if img_path and os.path.exists(img_path):
                    cpu = payload.get("cpu_usage", 0)
                    mem = payload.get("memory_usage", 0)
                    gpu = payload.get("gpu_usage")
                    status_text = f"📊 系统状态摘要：\n- 核心状态: {payload.get('overall_status')}\n- CPU: {cpu:.1f}%\n- 内存: {mem:.1f}%"
                    if gpu is not None:
                        status_text += f"\n- GPU: {gpu:.1f}%"
                    status_text += f"\n- 已加载模型: {payload.get('models_loaded')}/{payload.get('models_total')}"
                    status_text += f"\n- 累计记忆: {payload.get('memory_total', 0)} 条"
                    
                    await self.send_text(session_id, status_text)
                    await self.send_text(session_id, _build_cq_image(img_path))
                    return
            await self.send_text(
                session_id,
                _truncate_text(json.dumps(payload, ensure_ascii=False, indent=2), 1800),
            )
        except Exception as e:
            self.logger.error(f"Dashboard overview error: {e}")
            await self.send_text(session_id, f"状态错误: {e}")

    async def _show_dashboard_detail(self, session_id: str, prefs: dict, is_master: bool, section_key: str):
        try:
            data = await self.fetch_dashboard_data(session_id, prefs)
            health = data.get("health") if isinstance(data.get("health"), dict) else {}
            resources = data.get("resources") if isinstance(data.get("resources"), dict) else {}
            stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
            mem_stats = data.get("memory_stats") if isinstance(data.get("memory_stats"), dict) else {}
            sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []
            scheduled = data.get("scheduled") if isinstance(data.get("scheduled"), list) else []
            notifications = data.get("notifications") if isinstance(data.get("notifications"), list) else []
            life_status = data.get("life_status") if isinstance(data.get("life_status"), dict) else {}

            section_title = section_key
            items = []

            # (The original logic for constructing items is copied here)
            if section_key == "resources":
                section_title = "RESOURCES"
                metrics = health.get("metrics") if isinstance(health.get("metrics"), dict) else {}
                def _add(title, subtitle, status=None):
                    items.append({"title": title, "subtitle": subtitle, "status": status})

                _add("CPU", f"{float(metrics.get('cpu_usage') or resources.get('cpu_usage') or 0.0):.1f}%")
                _add("MEM", f"{float(metrics.get('memory_usage') or resources.get('memory_usage') or 0.0):.1f}%")
                if resources.get("has_gpu"):
                    _add("GPU", f"{float(metrics.get('gpu_usage') or resources.get('gpu_usage') or 0.0):.1f}%")
                    gpu = resources.get("gpu") if isinstance(resources.get("gpu"), dict) else {}
                    if gpu.get("name"):
                        _add("GPU_NAME", str(gpu.get("name")))
                _add("CPU_COUNT", str(resources.get("cpu_count") or "—"))
                _add("MEM_TOTAL", f"{float(resources.get('memory_total_gb') or 0.0):.1f} GB")
                _add("MEM_AVAIL", f"{float(resources.get('memory_available_gb') or 0.0):.1f} GB")
                if isinstance(stats, dict) and stats:
                    if "async_tasks" in stats:
                        _add("ASYNC_TASKS", str(stats.get("async_tasks")))
                    if "active_connections" in stats:
                        _add("ACTIVE_CONN", str(stats.get("active_connections")))

            elif section_key == "services":
                section_title = "SERVICES"
                services = health.get("services") if isinstance(health.get("services"), dict) else {}
                for name, payload in sorted(services.items(), key=lambda kv: str(kv[0])):
                    if isinstance(payload, dict):
                        st = payload.get("status")
                        details = payload.get("details")
                        if isinstance(details, dict):
                            detail_bits = []
                            for k in ("running", "next_llm_decision_in_seconds", "recent_errors"):
                                if k in details:
                                    detail_bits.append(f"{k}={details.get(k)}")
                            subtitle = ", ".join(detail_bits) if detail_bits else "—"
                        else:
                            subtitle = "—"
                        items.append({"title": name, "subtitle": subtitle, "status": st})
                    else:
                        items.append({"title": name, "subtitle": "—", "status": payload})

            elif section_key == "modules":
                section_title = "MODULES"
                active_raw = str(resources.get("active_model") or "—")
                active_display = os.path.basename(active_raw.replace("\\", "/")) if ("/" in active_raw or "\\" in active_raw) else active_raw
                items = [
                    {"title": "LLM_MODELS", "subtitle": f"loaded={resources.get('models_loaded')} / total={resources.get('models_total')}"},
                    {"title": "IMAGE_MODELS", "subtitle": str(resources.get("image_models_total") or "—")},
                    {"title": "VOICES", "subtitle": str(resources.get("voices_total") or "—")},
                    {"title": "ACTIVE_MODEL", "subtitle": active_display},
                    {"title": "CHAT_MODEL_HINT", "subtitle": str(prefs.get("chat_model") or "Default")},
                ]

            elif section_key == "memory":
                section_title = "MEMORY"
                counts = mem_stats.get("counts") if isinstance(mem_stats.get("counts"), dict) else {}
                dist = mem_stats.get("distribution") if isinstance(mem_stats.get("distribution"), dict) else {}
                avg = mem_stats.get("avg_weight") if isinstance(mem_stats.get("avg_weight"), dict) else {}
                total = mem_stats.get("total_memories")
                items.append({"title": "TOTAL_MEMORIES", "subtitle": str(total or "—")})
                try:
                    for cat, cnt in sorted(counts.items(), key=lambda kv: int(kv[1]), reverse=True)[:18]:
                        pct = dist.get(cat)
                        aw = avg.get(cat)
                        parts = [f"count={cnt}"]
                        if isinstance(pct, (int, float)):
                            parts.append(f"{float(pct):.1f}%")
                        if isinstance(aw, (int, float)):
                            parts.append(f"avg_w={float(aw):.2f}")
                        items.append({"title": cat, "subtitle": " ".join(parts)})
                except Exception:
                    pass

            elif section_key == "sessions":
                section_title = "SESSIONS"
                items.append({"title": "TOTAL", "subtitle": str(len(sessions))})
                for s in sessions[:18]:
                    if not isinstance(s, dict):
                        continue
                    sid = str(s.get("id") or "")
                    title = str(s.get("title") or sid or "session")
                    subtitle = f"id={sid}" if sid else "—"
                    items.append({"title": title, "subtitle": subtitle})

            elif section_key == "workspace":
                section_title = "SCHEDULE"
                items.append({"title": "PENDING_SCHEDULED", "subtitle": str(len(scheduled))})
                items.append({"title": "PENDING_NOTIFS", "subtitle": str(len(notifications))})
                for m in scheduled[:12]:
                    if not isinstance(m, dict):
                        continue
                    mid = str(m.get("id") or "")
                    ts = m.get("trigger_ts")
                    try:
                        ts_str = time.strftime("%m-%d %H:%M", time.localtime(float(ts))) if ts else "—"
                    except Exception:
                        ts_str = "—"
                    msg = str(m.get("message") or "")
                    if len(msg) > 50:
                        msg = msg[:49] + "…"
                    items.append({"title": ts_str, "subtitle": f"{msg} ({mid})" if mid else msg})

            elif section_key == "user":
                section_title = "USER"
                ud = data.get("user_status") if isinstance(data.get("user_status"), dict) else {}
                user = ud.get("user") if isinstance(ud.get("user"), dict) else {}
                aveline = ud.get("aveline") if isinstance(ud.get("aveline"), dict) else {}
                study = ud.get("study") if isinstance(ud.get("study"), dict) else {}
                items = [
                    {"title": "USER", "subtitle": f"{user.get('name')} L{user.get('level')} intimacy={user.get('intimacy')}"},
                    {"title": "AVELINE", "subtitle": f"emotion={aveline.get('emotion')} energy={aveline.get('energy')} mood={aveline.get('mood')}"},
                    {"title": "STUDY", "subtitle": f"learned={study.get('learned_words')}/{study.get('total_words')} today_reviews={study.get('today_reviews')}"},
                ]

            elif section_key == "bio":
                section_title = "BIO STATE"
                life = life_status.get("life") if isinstance(life_status.get("life"), dict) else {}
                bio = life_status.get("bio") if isinstance(life_status.get("bio"), dict) else {}
                immune = life_status.get("immune") if isinstance(life_status.get("immune"), dict) else {}

                def _kv(k, v, status=None):
                    items.append({"title": k, "subtitle": str(v), "status": status})

                _kv("MOOD", life_status.get("mood") or "—")
                _kv("ACTIVITY", life_status.get("activity") or "—")
                _kv("ENERGY", f"{float(life.get('energy', 0.0) or 0.0):.0f}/100")
                _kv("HUNGER", f"{float(life.get('hunger', 0.0) or 0.0):.0f}/100")
                _kv("THIRST", f"{float(life.get('thirst', 0.0) or 0.0):.0f}/100")
                _kv("MOOD_SCORE", f"{float(life.get('mood_score', 0.0) or 0.0):.0f}/100")
                _kv("SHYNESS", f"{float(life.get('shyness_score', 0.0) or 0.0):.0f}/100")
                _kv("IMMUNE_DAMAGE", f"{float(life.get('immune_damage', 0.0) or 0.0):.0f}/100", status="warning" if float(life.get('immune_damage', 0.0) or 0.0) >= 50 else "healthy")
                _kv("IS_SICK", str(bool(life.get("is_sick"))))
                _kv("LEVEL", str(int(life.get("level", 0) or 0)))
                _kv("XP", str(life.get("xp") or "—"))

                _kv("CPU_TEMP", f"{life_status.get('cpu_temp')}°C" if life_status.get("cpu_temp") is not None else "—")
                _kv("RAM_USAGE", f"{life_status.get('ram_usage')}%" if life_status.get("ram_usage") is not None else "—")
                _kv("BATTERY", f"{life_status.get('battery')}%" if life_status.get("battery") is not None else "—")
                _kv("LATENCY", str(life_status.get("network_latency") or "—"))
                _kv("VISION", str(life_status.get("vision_summary") or "—"))

                if bio:
                    for k in ("dopamine", "serotonin", "norepinephrine", "oxytocin", "cortisol", "sleep_debt"):
                        if k in bio:
                            _kv(k.upper(), bio.get(k))

                if immune:
                    _kv("UNHEALTHY_SVCS", str((immune.get("unhealthy_count") if immune.get("unhealthy_count") is not None else "—")))

            elif section_key == "emotion":
                section_title = "EMOTION"
                ud = data.get("user_status") if isinstance(data.get("user_status"), dict) else {}
                aveline = ud.get("aveline") if isinstance(ud.get("aveline"), dict) else {}

                emo_data = data.get("emotion")
                if isinstance(emo_data, dict) and emo_data:
                    top = max(emo_data, key=emo_data.get)
                    items.append({"title": "PRIMARY", "subtitle": str(top)})
                    for k, v in sorted(emo_data.items(), key=lambda kv: float(kv[1] or 0.0), reverse=True)[:18]:
                        try:
                            vv = float(v or 0.0)
                        except Exception:
                            vv = 0.0
                        items.append({"title": str(k), "subtitle": f"{vv:.3f}"})
                else:
                    items.append({"title": "PRIMARY", "subtitle": str(aveline.get("emotion") or "neutral")})

                mood = life_status.get("mood")
                if mood:
                    items.append({"title": "MOOD", "subtitle": str(mood)})

            if _HAS_STATUS_RENDERER and callable(generate_dashboard_detail_image):
                img_path = generate_dashboard_detail_image(section_title, items)
                if img_path and os.path.exists(img_path):
                    await self.send_text(session_id, _build_cq_image(img_path))
                    return
            await self.send_text(
                session_id,
                _truncate_text(
                    json.dumps({"title": section_title, "items": items}, ensure_ascii=False, indent=2),
                    1800,
                ),
            )
        except Exception as e:
            self.logger.error(f"Dashboard detail error: {e}")
            await self.send_text(session_id, f"状态错误: {e}")
