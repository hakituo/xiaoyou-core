from typing import Any, Dict, Optional, Tuple


async def handle_system_command(
    service: Any, user_input: str, conversation_id: str
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not user_input.startswith("/"):
        return None

    parts = user_input[1:].strip().split(" ", 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    from core.managers.preference_manager import get_preference_manager

    prefs = get_preference_manager()

    if cmd == "clear":
        if service.chat_agent:
            await service.chat_agent.clear_history(conversation_id, mode="all")
        return "记忆已清除。", {"status": "success", "command": "clear"}

    if cmd == "save":
        # 对话记录由 ChatHistoryStore 每轮自动持久化，这里触发偏好保存并返回确认
        try:
            await prefs.save_preferences()
            return "对话记录已自动保存，当前偏好配置已持久化。", {
                "status": "success",
                "command": "save",
            }
        except Exception as e:
            return f"保存失败: {e}", {"status": "error", "command": "save"}

    if cmd == "mode":
        mode = args.strip().lower()
        if mode in ["normal", "privacy", "study", "entertainment"]:
            old_mode = prefs.get_mode()
            await prefs.set_mode(mode)
            try:
                from core.services.active_care.core.service import get_active_care_service

                await get_active_care_service().on_mode_switch(mode, old_mode)
            except Exception:
                pass
            msg = f"已切换到【{mode}】模式。"
            if mode == "privacy":
                msg += " 本地优先，不上传敏感数据。"
            elif mode == "study":
                msg += " 专注学习，减少干扰。"
            elif mode == "entertainment":
                msg += " 祝你玩得开心！"
            return msg, {"status": "success", "command": "mode", "mode": mode}
        return (
            f"当前模式：{prefs.get_mode()}。可用模式：normal, privacy, study, entertainment",
            {"status": "info", "command": "mode"},
        )

    if cmd == "care":
        arg = args.strip().lower()
        if arg in ["on", "true", "enable", "1"]:
            await prefs.set_active_care(True)
            return "主动关怀已开启。我会适时找你聊天。", {
                "status": "success",
                "command": "care",
                "enabled": True,
            }
        if arg in ["off", "false", "disable", "0"]:
            await prefs.set_active_care(False)
            return "主动关怀已暂停。没有你的允许，我不会打扰你。", {
                "status": "success",
                "command": "care",
                "enabled": False,
            }
        current = "开启" if prefs.is_active_care_enabled() else "关闭"
        return (
            f"主动关怀当前状态：{current}。使用 /care on 或 /care off 切换。",
            {"status": "info", "command": "care"},
        )

    if cmd == "forget":
        if service.chat_agent:
            try:
                mm = service.chat_agent._get_memory_manager(conversation_id)
                count = 0
                if hasattr(mm, "short_term_memory"):
                    with mm.lock:
                        count = len(mm.short_term_memory)
                        mm.short_term_memory = []
                else:
                    await service.chat_agent.clear_history(
                        conversation_id, mode="short_term"
                    )
                return (
                    f"已清除最近的 {count} 条短期记忆。我们可以重新开始这个话题。",
                    {"status": "success", "command": "forget"},
                )
            except Exception as e:
                return f"清除记忆失败: {str(e)}", {
                    "status": "error",
                    "command": "forget",
                }
        return "无法访问记忆模块。", {"status": "error", "command": "forget"}

    if cmd == "memory":
        msg_count = 0
        try:
            if service.chat_agent:
                mm = service.chat_agent._get_memory_manager(conversation_id)
                with mm.lock:
                    msg_count = len(getattr(mm, "short_term_memory", []) or []) + len(
                        getattr(mm, "weighted_memories", {}) or {}
                    )
        except Exception:
            msg_count = 0
        from core.services.monitoring.system_memory_service import get_system_memory_manager

        sys_mem = get_system_memory_manager()
        mem_info = ""
        if sys_mem:
            stats = sys_mem.get_memory_stats()
            rss = stats["monitor_info"]["process_rss_mb"]
            mem_info = f"\n系统占用: {rss:.1f}MB"
        return (
            f"当前记忆状态：\n对话轮数: {msg_count // 2}\n消息总数: {msg_count}{mem_info}",
            {"status": "success", "command": "memory"},
        )

    if cmd == "latency":
        from config.integrated_config import get_settings

        settings = get_settings()
        arg = args.strip().lower()
        if arg in ["on", "true", "enable", "1", "开启"]:
            settings.scheduler.bio_enable_cognitive_delay = True
            return "仿生学认知延迟已开启。回复会带有模拟思考的时间延迟。", {
                "status": "success",
                "command": "latency",
                "enabled": True,
            }
        if arg in ["off", "false", "disable", "0", "关闭"]:
            settings.scheduler.bio_enable_cognitive_delay = False
            return (
                "仿生学认知延迟已关闭。系统将以最快速度响应（低首 token 延迟模式）。",
                {"status": "success", "command": "latency", "enabled": False},
            )
        current = "开启" if settings.scheduler.bio_enable_cognitive_delay else "关闭"
        return (
            f"当前仿生延迟状态：{current}。使用 /latency on 或 /latency off 切换。",
            {"status": "info", "command": "latency"},
        )

    if cmd in {"studylog", "study"}:
        raw = args.strip()
        if not raw:
            return (
                "用法：/studylog 主题|内容  或  /studylog 内容",
                {"status": "info", "command": "studylog"},
            )
        if "|" in raw:
            topic, content = raw.split("|", 1)
            topic = topic.strip() or "学习"
            content = content.strip()
        else:
            topic = "学习"
            content = raw
        if not content:
            return (
                "学习记录内容不能为空。",
                {"status": "error", "command": "studylog"},
            )
        from core.services.workspace.service import get_workspace_service

        ws = get_workspace_service()
        data = await ws.record_study_progress(topic=topic, content=content)
        return (
            f"已记录学习：{topic}｜{content}",
            {"status": "success", "command": "studylog", "data": data},
        )

    if cmd in {"studydone", "studyfinish"}:
        content = args.strip() or "结束本轮学习"
        from core.services.workspace.service import get_workspace_service

        ws = get_workspace_service()
        data = await ws.record_study_progress(topic="学习收尾", content=content)
        try:
            from core.managers.preference_manager import get_preference_manager

            await get_preference_manager().set_mode("normal")
        except Exception:
            pass
        return (
            f"已记录学习收尾：{content}",
            {"status": "success", "command": "studydone", "data": data},
        )

    if cmd in {"studypanel", "panelstudy"}:
        from core.services.workspace.service import get_workspace_service

        ws = get_workspace_service()
        panel = await ws.get_learning_panel_bundle(
            conversation_id=conversation_id,
            history_limit=20,
        )
        study_panel = panel.get("study_panel") or {}
        daily_summary = (study_panel.get("daily_summary") or {})
        vocab = (daily_summary.get("vocab") or {})
        session = (daily_summary.get("session") or {})
        snapshot = panel.get("workspace_snapshot") or {}
        portrait = (snapshot.get("portrait") or {})
        study_sessions = (portrait.get("study") or {}).get("sessions") or []
        recent_chat = panel.get("recent_chat_history") or []
        return (
            "学习面板（实时）\n"
            f"- 待复习: {int(vocab.get('to_review') or 0)}\n"
            f"- 每日目标: {int(vocab.get('daily_quota') or 20)}\n"
            f"- 今日已复习: {int(session.get('words_reviewed') or 0)}\n"
            f"- 连续学习: {int(study_panel.get('study_streak_days') or 0)} 天\n"
            f"- 今日学习记录: {len(study_sessions)} 条\n"
            f"- 最近聊天: {len(recent_chat)} 条\n"
            "说明：待复习是累计欠账，不受每日20新词上限约束。",
            {"status": "success", "command": "studypanel", "data": panel},
        )

    if cmd in {"statistics", "stats"}:
        # P1-6: 综合统计（复用 WorkspaceService + 系统资源）
        try:
            from core.services.workspace.service import get_workspace_service
            from core.services.monitoring.system_memory_service import get_system_memory_manager

            ws = get_workspace_service()
            panel = await ws.get_learning_panel_bundle(
                conversation_id=conversation_id, history_limit=20
            )
            pending_reminders = await ws.get_pending_messages()

            # 对话历史条数
            chat_count = 0
            try:
                from core.services.chat_history_store import get_chat_history_store
                events = get_chat_history_store().list_conversation_events(
                    conversation_id, limit=10000
                )
                chat_count = len(events)
            except Exception:
                pass

            # 记忆条数
            memory_count = 0
            try:
                if service.chat_agent:
                    mm = service.chat_agent._get_memory_manager(conversation_id)
                    with mm.lock:
                        memory_count = len(getattr(mm, "weighted_memories", {}) or {})
            except Exception:
                pass

            # 学习面板数据
            study_panel = panel.get("study_panel") or {}
            daily_summary = study_panel.get("daily_summary") or {}
            vocab = daily_summary.get("vocab") or {}
            session = daily_summary.get("session") or {}

            # 系统资源
            sys_mem = get_system_memory_manager()
            rss_mb = 0.0
            if sys_mem:
                stats = sys_mem.get_memory_stats()
                rss_mb = stats["monitor_info"]["process_rss_mb"]

            # 用户面板
            user_panel = panel.get("user_panel") or {}
            intimacy = float(user_panel.get("intimacy") or 0)
            life_state = user_panel.get("life_state") or {}
            # life_state 结构：mood 是字符串，energy 在 life 子字典里
            mood_str = str(life_state.get("mood") or "unknown")
            life_sub = life_state.get("life") or {}
            energy_val = 100
            try:
                energy_val = float(life_sub.get("energy") or 100)
            except (ValueError, TypeError):
                pass
            activity_str = str(life_state.get("activity") or "unknown")

            lines = [
                "【综合统计】",
                f"对话条数: {chat_count}",
                f"记忆条数: {memory_count}",
                f"待触发提醒: {len(pending_reminders)}",
                "",
                "【学习】",
                f"连续学习: {int(study_panel.get('study_streak_days') or 0)} 天",
                f"今日复习: {int(session.get('words_reviewed') or 0)}",
                f"待复习: {int(vocab.get('to_review') or 0)}",
                f"每日目标: {int(vocab.get('daily_quota') or 20)}",
                "",
                "【角色状态】",
                f"亲密度: {intimacy:.1f}",
                f"能量: {energy_val:.0f}",
                f"心情: {mood_str}",
                f"当前活动: {activity_str}",
                "",
                "【系统】",
                f"进程内存: {rss_mb:.1f}MB",
            ]
            return "\n".join(lines), {
                "status": "success",
                "command": "statistics",
            }
        except Exception as e:
            return f"统计获取失败: {e}", {"status": "error", "command": "statistics"}

    if cmd == "export":
        # P1-6: 导出数据到文件
        target = args.strip().lower() or "all"
        if target not in {"chat", "diary", "memory", "all"}:
            return (
                "用法：/export [chat|diary|memory|all]\n"
                "  chat - 对话历史\n  diary - 日记\n  memory - 记忆\n  all - 全部",
                {"status": "info", "command": "export"},
            )
        try:
            import json
            from core.utils.data_paths import get_user_data_dir
            from core.utils.time_utils import get_current_time

            export_dir = get_user_data_dir() / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            ts_str = get_current_time().strftime("%Y%m%d_%H%M%S")
            exported_files = []

            # 导出对话历史
            if target in {"chat", "all"}:
                try:
                    from core.services.chat_history_store import get_chat_history_store
                    events = get_chat_history_store().list_conversation_events(
                        conversation_id, limit=100000
                    )
                    chat_file = export_dir / f"chat_{ts_str}.json"
                    chat_file.write_text(
                        json.dumps(events, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    exported_files.append(f"chat: {chat_file.name} ({len(events)} 条)")
                except Exception as e:
                    exported_files.append(f"chat: 失败 ({e})")

            # 导出日记
            if target in {"diary", "all"}:
                try:
                    from core.services.journal.service import get_journal_service
                    entries = await get_journal_service().get_entries(None)
                    diary_data = [e.model_dump() for e in entries]
                    diary_file = export_dir / f"diary_{ts_str}.json"
                    diary_file.write_text(
                        json.dumps(diary_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    exported_files.append(f"diary: {diary_file.name} ({len(diary_data)} 条)")
                except Exception as e:
                    exported_files.append(f"diary: 失败 ({e})")

            # 导出记忆
            if target in {"memory", "all"}:
                try:
                    if service.chat_agent:
                        mm = service.chat_agent._get_memory_manager(conversation_id)
                        with mm.lock:
                            memories = []
                            weighted = getattr(mm, "weighted_memories", {}) or {}
                            for mid, m in weighted.items():
                                if hasattr(m, "model_dump"):
                                    memories.append(m.model_dump())
                                elif isinstance(m, dict):
                                    memories.append(m)
                            memory_file = export_dir / f"memory_{ts_str}.json"
                            memory_file.write_text(
                                json.dumps(memories, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                            exported_files.append(
                                f"memory: {memory_file.name} ({len(memories)} 条)"
                            )
                    else:
                        exported_files.append("memory: 跳过（无 chat_agent）")
                except Exception as e:
                    exported_files.append(f"memory: 失败 ({e})")

            return (
                f"导出完成，目录: {export_dir}\n" + "\n".join(exported_files),
                {"status": "success", "command": "export", "dir": str(export_dir)},
            )
        except Exception as e:
            return f"导出失败: {e}", {"status": "error", "command": "export"}

    if cmd == "backup":
        # P1-6: 备份全部用户数据为 zip
        # 注意：shutil.make_archive 没有 ignore 参数，必须用 zipfile 手动打包
        # 并跳过 backups/exports 目录，否则会递归打包导致文件越来越大
        try:
            import zipfile
            from pathlib import Path
            from core.utils.data_paths import get_user_data_dir
            from core.utils.time_utils import get_current_time

            user_dir = get_user_data_dir()
            backup_dir = user_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts_str = get_current_time().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"backup_{ts_str}.zip"
            zip_path = backup_dir / zip_filename

            # 需要跳过的子目录名（避免递归打包 backups 自身）
            skip_dirs = {"backups", "exports"}

            file_count = 0
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in user_dir.rglob("*"):
                    # 跳过 backups/exports 目录及其内容
                    rel = item.relative_to(user_dir)
                    if any(part in skip_dirs for part in rel.parts):
                        continue
                    if item.is_file():
                        zf.write(item, rel)
                        file_count += 1

            zip_size = zip_path.stat().st_size
            size_str = (
                f"{zip_size / 1024 / 1024:.2f}MB"
                if zip_size > 1024 * 1024
                else f"{zip_size / 1024:.1f}KB"
            )

            return (
                f"备份完成: {zip_filename}\n大小: {size_str}\n文件数: {file_count}\n目录: {backup_dir}",
                {
                    "status": "success",
                    "command": "backup",
                    "path": str(zip_path),
                    "size": zip_size,
                },
            )
        except Exception as e:
            return f"备份失败: {e}", {"status": "error", "command": "backup"}

    if cmd == "help":
        # P0-1/P1-7: 从命令注册中心动态生成，确保与注册表一致
        from core.services.aveline.command_registry import format_help_text

        return format_help_text(), {"status": "success", "command": "help"}

    return None
