"""静态检查安卓选择的保存、恢复和发送契约；不替代 Android 编译及设备验收。"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"


def read(path: str) -> str:
    """去掉注释，避免仅修改注释就误通过验证。"""
    source = (ANDROID / path).read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def body(source: str, name: str) -> str:
    """按四空格缩进提取成员函数。"""
    match = re.search(r"fun " + name + r"\(.*?\n    \}", source, re.S)
    assert match, f"找不到函数 {name}"
    return match.group()


def main() -> None:
    prefs = read("data/local/preferences/AppPreferences.kt")
    assert 'prefs.getString("selected_model_route", "")' in prefs
    assert 'putString("selected_model_route", value).apply()' in prefs
    assert 'prefs.getString("selected_persona:$role", null)' in prefs
    assert 'putString("selected_persona:$role", filename).apply()' in prefs

    plugins = read("data/repository/PluginsRepositoryImpl.kt")
    selected = body(plugins, "getSelectedModel")
    assert selected.index("appPreferences.selectedModelId") < selected.index("backendSelectedModelId")
    switch = body(plugins, "switchModel")
    assert switch.index("if (!response.success)") < switch.index("appPreferences.selectedModelRoute = modelPath")
    assert "cachedModelRoutes[appPreferences.selectedModelId]" in plugins
    chat = read("data/repository/ChatRepositoryImpl.kt")
    assert chat.count("model = resolveRequestModel(model)") == 3
    resolver = body(chat, "resolveRequestModel")
    assert resolver.index("return model") < resolver.index("appPreferences.selectedModelRoute")

    controller = read("presentation/chat/ChatSessionController.kt")
    pending = body(controller, "setPendingSwitch")
    assert pending.index("getSelectedPersona(role)") < pending.index("preferredFilename?.")
    confirmed = body(controller, "confirmPersonaSelection")
    for value in (
        "setSelectedPersona(role, filename)",
        "pendingSwitchFilename = filename",
        "pendingSwitchConsumed = true",
        "currentPersonaFilename = filename",
        "_viewingPersonaFilename.value = filename",
        "ensureRoleSession(role, filename)",
    ):
        assert value in confirmed, value
    consume = body(controller, "consumePendingSwitchIfNeeded")
    assert ".getOrThrow()" in consume
    assert "confirmPersonaSelection(targetFilename)" in consume
    assert "ensureRoleSession(role, personaFilename)" in body(controller, "switchLocalSession")
    assert "currentRole != expectedRole" in body(controller, "switchLocalSessionId")
    assert "get() = pendingSwitchFilename ?: currentPersonaFilename" in controller

    persona = body(read("presentation/persona/PersonaViewModel.kt"), "switchPersona")
    assert persona.index("selectPersona(filename).getOrThrow()") < persona.index("onSelected(filename)")
    screen = read("presentation/chat/ChatScreen.kt")
    panel = read("presentation/chat/ChatCompanionPanel.kt")
    assert "chatViewModel.confirmPersonaSelection(selected)" in panel
    assert "ChatCompanionPanel(" in screen
    assert "viewModel.setViewingPersona(fn)" not in screen
    listing = read("presentation/conversations/ConversationListViewModel.kt")
    assert "getSelectedPersona(role)" in listing
    assert listing.index("it.filename == savedFilename") < listing.index("list.firstOrNull { it.isActive }")

    sender = read("presentation/chat/ChatSendController.kt")
    send = body(sender, "sendMessage")
    assert send.index("consumePendingSwitchIfNeeded()") < send.index("val sessionId =")
    assert "return@launch" in send
    assert "chatRepository.observeMessageWindow(sessionId, 200).first().messages" in send
    assert send.index("loadHistoryFromApi(sessionId).getOrThrow()") < send.index("observeMessageWindow")
    assert "sessionController.conversationPersonaFilename" in sender
    print("PASS: 模型持久化和三种请求、人设确认和角色恢复、失败阻断及会话隔离静态契约")


if __name__ == "__main__":
    main()
