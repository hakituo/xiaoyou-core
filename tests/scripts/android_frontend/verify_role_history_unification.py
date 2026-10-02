"""检查稳定角色协议和安卓迁移接线；不替代 Room/Kotlin 与真机验收。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from routers.v1.personas import _resolve_role_identity  # noqa: E402

ANDROID = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"


def main():
    """验证真实注册表映射，并防止迁移或持久化链路被断开。"""
    for filename, display, scope in (
        ("core_aveline.json", "Aveline", "aveline"),
        ("core_ling.json", "Ling", "ling"),
    ):
        original = {"filename": filename, "role": display}
        identity = _resolve_role_identity(original)
        assert original["role"] == display
        assert identity["role_id"] == scope
        assert {display, scope} <= set(identity["role_aliases"])

    repo = (ANDROID / "data/repository/ChatRepositoryImpl.kt").read_text(encoding="utf-8")
    assert "messageDao.deleteOldestMessages(" not in repo
    assert repo.index("messageDao.mergeRoleHistory(target, candidates.sorted())") < repo.index("roleScopedPreferences.completeRoleMigration")
    assert "resolveStoredMessage(message)" in repo
    assert "mergedMessageId(source, id)" in repo
    dao = (ANDROID / "data/local/database/dao/MessageDao.kt").read_text(encoding="utf-8")
    assert "@Transaction\n    suspend fun mergeRoleHistory" in dao
    assert "archiveSourceMessages(source, archive)" in dao
    assert "getMessageCount(targetSessionId)" in dao
    assert "suspend fun insertHistoryIfEmpty" in dao
    persona = (ANDROID / "data/repository/PersonaRepositoryImpl.kt").read_text(encoding="utf-8")
    assert persona.index("historyMigration.migrate(personas)") < persona.index("Result.success(personas)")
    controller = (ANDROID / "presentation/chat/ChatSessionController.kt").read_text(encoding="utf-8")
    active = controller.split("personaRepository.observeActivePersona()", 1)[1].split("suspend fun ensureSessionForCurrentPersona", 1)[0]
    assert "ensureSessionForCurrentPersona()" not in active
    print("PASS: 稳定 role_id、旧键合并归档、重试和迟到消息重定向、长期保存静态契约")


if __name__ == "__main__":
    main()
