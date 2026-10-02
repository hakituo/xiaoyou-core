"""验证 Android 聊天消息编辑、重新生成和版本分支接线。"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
ANDROID = ROOT / "clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile"


def require(path: Path, fragment: str, description: str) -> None:
    """断言源码包含关键实现。"""
    source = path.read_text(encoding="utf-8")
    if fragment not in source:
        raise AssertionError(f"{description}缺失: {path} -> {fragment}")


def main() -> None:
    """执行消息树、UI 操作、分支上下文和关系记忆的静态回归检查。"""
    message = ANDROID / "domain/models/Message.kt"
    entity = ANDROID / "data/local/database/entity/MessageEntity.kt"
    database = ANDROID / "data/local/database/AvelineDatabase.kt"
    dao = ANDROID / "data/local/database/dao/MessageDao.kt"
    repository_contract = ANDROID / "domain/repository/ChatRepository.kt"
    repository = ANDROID / "data/repository/ChatRepositoryImpl.kt"
    controller = ANDROID / "presentation/chat/ChatSendController.kt"
    bubble = ANDROID / "presentation/components/MessageBubble.kt"
    screen = ANDROID / "presentation/chat/ChatScreen.kt"
    request = ANDROID / "data/remote/dto/MessageRequest.kt"
    router = ROOT / "routers/v1/chat.py"
    context = ROOT / "core/agents/chat_agent_components/context.py"
    branch = ROOT / "core/agents/chat_agent_components/message_branch.py"
    storage = ROOT / "memory/core/storage.py"
    relation_graph = ROOT / "memory/core/relation_graph.py"

    for path in (message, entity):
        require(path, "val parentId: String? = null", "父消息字段")
        require(path, "val variantIndex: Int = 0", "版本序号字段")

    # 后续数据库升级仍应保留消息树和迁移，不能把当前版本固定为最早引入的 v4。
    version = re.search(r"version\s*=\s*(\d+)", database.read_text(encoding="utf-8"))
    assert version and int(version.group(1)) >= 4, "Room 必须支持 v4 消息树及后续迁移"
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

    require(request, "data class MessageBranchMetadata", "Android 分支关系协议")
    require(request, "val user_parent_id:", "用户父节点上传")
    require(request, "val assistant_variant_of:", "AI 重生成版本关系上传")
    require(request, "branch_metadata?.assistant_message_id", "客户端稳定 turn ID")
    require(repository_contract, "data class ChatBranchContext", "领域层分支事务")
    require(repository, "branch_metadata = branchContext?.toRequestMetadata()", "网络层分支关系上传")
    require(controller, "userVariantOfId = original.id", "用户编辑 variant_of")
    require(controller, "assistantVariantOfId = original.id", "AI 重生成 variant_of")
    require(controller, "ChatBranchContext(", "生成事务冻结消息树关系")

    require(request, "val history_override:", "Android 分支历史协议")
    require(router, 'message.get("history_override")', "后端分支历史解析")
    require(context, "if history_override is not None:", "后端分支上下文覆盖")
    require(router, 'message.get("branch_metadata")', "后端关系元数据解析")
    require(router, "set_request_branch_metadata", "请求级分支上下文绑定")
    require(branch, "ContextVar", "并发请求关系隔离")
    require(storage, 'metadata.get("client_message_id")', "WeightedMemory 客户端节点落库")
    require(storage, "_client_dedupe_key", "客户端节点独立去重")
    require(relation_graph, "_build_client_id_aliases", "客户端 ID 到记忆 UUID 映射")
    require(relation_graph, "_build_branch_lineages", "父链世界线恢复")
    require(relation_graph, "_lineages_compatible", "兄弟世界线隔离")

    print(
        "PASS: Android 聊天请求编辑、回复重生成、版本切换、分支上下文及关系记忆同步已完整接线。"
    )


if __name__ == "__main__":
    main()
