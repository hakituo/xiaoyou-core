"""Static regression checks for Android role-scoped chat state.

This script intentionally has no third-party dependencies so it can be run from the
repository root before an Android build. It guards the state-boundary mistakes that
caused one role's model/persona changes to affect another role's chat.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require(text: str, needle: str, label: str) -> None:
    assert needle in text, f"missing {label}: {needle}"


def forbid(text: str, needle: str, label: str) -> None:
    assert needle not in text, f"forbidden {label}: {needle}"


def main() -> None:
    role_model = read(
        "clients/frontend/aveline-android/android/app/src/main/java/"
        "com/aveline/ai/mobile/presentation/chat/RoleModelController.kt"
    )
    send = read(
        "clients/frontend/aveline-android/android/app/src/main/java/"
        "com/aveline/ai/mobile/presentation/chat/ChatSendController.kt"
    )
    session = read(
        "clients/frontend/aveline-android/android/app/src/main/java/"
        "com/aveline/ai/mobile/presentation/chat/ChatSessionController.kt"
    )
    view_model = read(
        "clients/frontend/aveline-android/android/app/src/main/java/"
        "com/aveline/ai/mobile/presentation/chat/ChatViewModel.kt"
    )
    role_prefs = read(
        "clients/frontend/aveline-android/android/app/src/main/java/"
        "com/aveline/ai/mobile/data/local/preferences/RoleScopedPreferences.kt"
    )
    backend = read("routers/v1/chat.py")

    # Role model selection is persisted locally and never calls the global switch API.
    require(role_model, "preferences.setModel(role, model.id, route)", "role model persistence")
    require(role_model, "fun requestModelRoute(): String?", "request-scoped route accessor")
    forbid(role_model, "pluginsRepository.switchModel(", "global model switching from role UI")

    # Every assistant generation path funnels through requestModel in ChatSendController.
    require(send, "val requestModel = resolveRoleModelRoute()", "per-request role model resolution")
    require(send, "requestModel,", "role model passed to repository")
    require(view_model, "resolveRoleModelRoute = { roleModelController.requestModelRoute() }", "ViewModel wiring")

    # Role is the session boundary; persona only selects prompt/version.
    require(role_prefs, "fun getSessionId(role: String)", "role session persistence")
    require(session, "roleScopedPreferences.getSessionId(role)", "role session lookup")
    require(session, "ensureRoleSession(role, filename)", "persona switch keeping role session")

    # Keep the unread behavior introduced on main while changing the session boundary.
    require(session, "personaLocalMetaRepository.clearUnread(filename)", "unread clearing")
    require(view_model, "personaLocalMetaRepository = personaLocalMetaRepository", "unread repository wiring")

    # Backend accepts Android's body fields as request-scoped hints and only falls back
    # to persona-derived history for legacy clients that omitted an explicit session id.
    require(backend, 'message.get("model")', "body model override")
    require(backend, 'message.get("session_id")', "body session id")
    require(backend, "if persona_filename and not conversation_id:", "legacy persona cid fallback")

    print("role-scoped chat validation: PASS")


if __name__ == "__main__":
    main()
