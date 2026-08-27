"""验证 Android 聊天消息编辑、重新生成和版本分支接线。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ANDROID = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"


def require(path: Path, fragment: str, description: str) -> None:
    """断言源码包含关键实现。"""
    source = path.read_text(encoding="utf-8")
    if fragment not in source:
        raise AssertionError(f"{description}缺失: {path} -> {fragment}")


def main() -> None:
    """执行消息树、UI 操作和分支上下文的静态回归检查。"""
    message = ANDROID / "domain/models/Message.kt"
    entity = ANDROID / "data/local/database/entity/MessageEntity.kt"
    database = ANDROID / "data/local/database/AvelineDatabase.kt"
    dao = ANDROID / "data/local/database/dao/MessageDao.kt"
    repository = ANDROID / "data/repository/ChatRepositoryImpl.kt"
    controller = ANDROID / "presentation/chat/ChatSendController.kt"
    bubble = ANDROID / "presentation/components/MessageBubble.kt"
    screen = ANDROID / "presentation/chat/ChatScreen.kt"
    request = ANDROID / "data/remote/dto/MessageRequest.kt"
    router = ROOT / "routers/v1/chat.py"
    context = ROOT / "core/agents/chat_agent_components/context.py"

    for path in (message, entity):
        require(path, "val parentId: String? = null", "父消息字段")
        require(path, "val variantIndex: Int = 0", "版本序号字段")

    require(database, "version = 4", "Room 数据库版本")
    require(database, "MIGRATION_3_4", "旧消息迁移")
    require(dao, "suspend fun insertActiveVariant", "原子插入新版本")
    require(dao, "suspend fun selectVariant", "原子切换版本")
    require(repository, "selectActiveConversationPath", "当前分支路径提取")
    require(controller, "fun regenerateMessage", "AI 重新生成入口")
    require(controller, "fun editUserMessage", "用户请求编辑入口")
    require(controller, "fun selectVariant", "版本切换入口")
    require(controller, "prefixHistory", "选中分支上下文传递")
    require(bubble, 'contentDescription = "重新生成"', "重新生成按钮")
    require(bubble, 'contentDescription = "编辑请求"', "编辑按钮")
    require(bubble, 'text = "${message.variantIndex + 1} / ${message.variantCount}"', "版本计数器")
    require(screen, "viewModel.editUserMessage", "编辑弹窗提交")
    require(screen, "viewModel.regenerateMessage", "重新生成 UI 接线")
    require(request, "val history_override:", "Android 分支历史协议")
    require(router, 'message.get("history_override")', "后端分支历史解析")
    require(context, "if history_override is not None:", "后端分支上下文覆盖")

    print("PASS: Android 聊天请求编辑、回复重生成、版本切换及分支上下文已完整接线。")


if __name__ == "__main__":
    main()
