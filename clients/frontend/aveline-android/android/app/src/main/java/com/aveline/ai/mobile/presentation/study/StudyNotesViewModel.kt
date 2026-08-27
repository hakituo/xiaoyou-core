package com.aveline.ai.mobile.presentation.study

import android.content.Context
import androidx.collection.LruCache
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.DailyNoteContent
import com.aveline.ai.mobile.domain.models.LibraryNote
import com.aveline.ai.mobile.domain.repository.StudyRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject

/**
 * 知识笔记（学习库）域 ViewModel。
 *
 * 从 [StudyDailyViewModel] 中拆分出来,独立管理学习库笔记的列表加载、内容读取与缓存。
 *
 * 缓存策略（两层）：
 * - 内存 [LruCache]：以 rel_path 为 key 缓存已加载的笔记正文,避免同一次会话内重复网络/IO。
 * - 磁盘 [NotesCache]：单向镜像后端（后端 → 手机本地,只读）,离线可读、跨会话保留。
 *
 * @property context ApplicationContext（用于磁盘缓存）
 * @property studyRepository 学习仓库（读取笔记列表与内容）
 */
@HiltViewModel
class StudyNotesViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val studyRepository: StudyRepository
) : ViewModel() {

    /** 内存缓存：rel_path -> 笔记正文 */
    private val memoryCache = LruCache<String, String>(64)

    /** 磁盘缓存：单向镜像后端学习库 */
    private val diskCache = NotesCache(context)

    private val _uiState = MutableStateFlow(StudyNotesUiState())
    val uiState: StateFlow<StudyNotesUiState> = _uiState.asStateFlow()

    /**
     * 加载学习库笔记列表(Study 根目录下各科目文件夹的 .md 文件)。
     * 列表拉到后同步 index 到磁盘缓存（仅记录 ts,不拉内容），
     * 并构建为文件夹树 [NoteTreeNode] 供 UI 层级展示。
     */
    fun loadLibraryNotes() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            studyRepository.getLibraryNotes()
                .onSuccess { notes ->
                    withContext(Dispatchers.IO) {
                        notes.filter { !it.isHidden() }.forEach { note ->
                            if (diskCache.needsRefresh(note.relPath, note.updatedTs)) {
                                val existing = diskCache.readContent(note.relPath)
                                diskCache.write(note.relPath, existing ?: "", note.updatedTs)
                            }
                        }
                    }
                    val visibleNotes = notes.filter { !it.isHidden() }
                    _uiState.update {
                        it.copy(
                            libraryNotes = visibleNotes,
                            noteTree = buildNoteTree(visibleNotes),
                            isLoading = false
                        )
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载学习库失败")
                    }
                }
        }
    }

    /**
     * 加载学习库中指定笔记内容(按相对路径)。
     *
     * 命中顺序：内存 LruCache → 磁盘缓存(未过期) → 后端。
     * 从后端取到后同时写回内存与磁盘缓存。
     *
     * @param path 相对于学习根目录的路径,如 "Mathematics/极限.md"
     */
    fun loadLibraryNote(path: String) {
        // 内存命中直接展示,避免任何 IO
        memoryCache.get(path)?.let { cached ->
            _uiState.update {
                it.copy(
                    currentNoteContent = DailyNoteContent(
                        filename = path.substringAfterLast("/"),
                        path = path,
                        content = cached
                    )
                )
            }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            // 磁盘命中(内容已存在)则直接读本地
            val disk = withContext(Dispatchers.IO) { diskCache.readContent(path) }
            if (!disk.isNullOrBlank()) {
                memoryCache.put(path, disk)
                _uiState.update {
                    it.copy(
                        currentNoteContent = DailyNoteContent(
                            filename = path.substringAfterLast("/"),
                            path = path,
                            content = disk
                        ),
                        isLoading = false
                    )
                }
                return@launch
            }
            // 走后端
            studyRepository.getLibraryNote(path)
                .onSuccess { content ->
                    withContext(Dispatchers.IO) {
                        memoryCache.put(content.path, content.content)
                        diskCache.write(content.path, content.content, System.currentTimeMillis() / 1000)
                    }
                    _uiState.update {
                        it.copy(currentNoteContent = content, isLoading = false)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载笔记内容失败")
                    }
                }
        }
    }

    /**
     * 打开指定笔记进入阅读页，并触发内容加载（内存/磁盘/后端三级缓存）。
     *
     * 切换文件时先清空旧内容，避免阅读页短暂显示上一篇笔记。
     *
     * @param path 笔记相对路径，如 "Biology/08_专项练习/01_分子与细胞/笔记.md"
     */
    fun openNote(path: String) {
        _uiState.update {
            it.copy(
                selectedNotePath = path,
                isReaderOpen = true,
                currentNoteContent = null
            )
        }
        loadLibraryNote(path)
    }

    /** 关闭阅读页 */
    fun closeReader() {
        _uiState.update { it.copy(isReaderOpen = false) }
    }

    /** 清除错误信息 */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}

/**
 * 知识笔记域 UI 状态。
 *
 * @property libraryNotes 学习库笔记列表(按后端返回顺序)
 * @property noteTree 文件夹树（顶层为科目文件夹）
 * @property currentNoteContent 当前打开的笔记内容
 * @property selectedNotePath 当前打开的笔记相对路径
 * @property isReaderOpen 是否显示阅读页
 * @property isLoading 是否加载中
 * @property error 错误信息
 */
data class StudyNotesUiState(
    val libraryNotes: List<LibraryNote> = emptyList(),
    val noteTree: List<NoteTreeNode> = emptyList(),
    val currentNoteContent: DailyNoteContent? = null,
    val selectedNotePath: String? = null,
    val isReaderOpen: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null
)

/**
 * 学习库笔记文件夹树节点。
 */
sealed class NoteTreeNode {
    abstract val name: String
    abstract val path: String

    /** 文件夹节点 */
    data class Folder(
        override val name: String,
        override val path: String,
        val children: List<NoteTreeNode>
    ) : NoteTreeNode()

    /** 文件节点 */
    data class File(
        override val name: String,
        override val path: String,
        val note: LibraryNote
    ) : NoteTreeNode()

    /** 递归统计该节点下（含子目录）的 .md 文件数量 */
    fun fileCount(): Int = when (this) {
        is File -> 1
        is Folder -> children.sumOf { it.fileCount() }
    }
}

/** 判断笔记路径是否包含隐藏目录/文件（防御性过滤） */
private fun LibraryNote.isHidden(): Boolean =
    relPath.split("/").any { it.startsWith(".") } || filename.startsWith(".")

/**
 * 将扁平的 [LibraryNote] 列表构建为文件夹树。
 *
 * 顶层节点为科目文件夹（subject），下面按 relPath 的目录层级递归展开。
 * 返回结果按名称排序。
 */
private fun buildNoteTree(notes: List<LibraryNote>): List<NoteTreeNode.Folder> {
    // 按 subject 分组，组内按 relPath 排序
    val grouped = notes.groupBy { it.subject }.toSortedMap(String.CASE_INSENSITIVE_ORDER)
    return grouped.map { (subject, subjectNotes) ->
        // 把每个 note 的 relPath 去掉 subject 前缀后的部分作为相对路径
        val root = mutableMapOf<String, NoteTreeNode>()
        subjectNotes.sortedBy { it.relPath.lowercase() }.forEach { note ->
            val parts = note.relPath.split("/")
            // parts[0] 为 subject，剩余部分为子路径
            val tailParts = parts.drop(1)
            insertNote(root, tailParts, note, note.relPath)
        }
        NoteTreeNode.Folder(
            name = subject,
            path = subject,
            children = root.values.sortedWith(compareBy({ it !is NoteTreeNode.Folder }, { it.name.lowercase() }))
        )
    }
}

/**
 * 递归把文件插入到文件夹树。
 *
 * @param map 当前层级的节点映射（path -> node）
 * @param remainingParts 当前 note 在 subject 之下的剩余路径段
 * @param note 原始笔记
 * @param fullRelPath 完整相对路径
 */
private fun insertNote(
    map: MutableMap<String, NoteTreeNode>,
    remainingParts: List<String>,
    note: LibraryNote,
    fullRelPath: String
) {
    if (remainingParts.isEmpty()) return
    val head = remainingParts.first()
    val currentPath = if (remainingParts.size == 1) fullRelPath else fullRelPath
    // 当前层级的完整路径：用原 relPath 截断到当前深度
    val depth = note.relPath.split("/").size - remainingParts.size
    val pathParts = note.relPath.split("/").take(depth + 1)
    val nodePath = pathParts.joinToString("/")

    if (remainingParts.size == 1) {
        // 叶子：文件
        map[nodePath] = NoteTreeNode.File(
            name = head.removeSuffix(".md"),
            path = note.relPath,
            note = note
        )
    } else {
        // 中间节点：文件夹
        val folder = map[nodePath] as? NoteTreeNode.Folder
            ?: NoteTreeNode.Folder(name = head, path = nodePath, children = emptyList())
        val childMap = folder.children.toMutableMapByPath()
        insertNote(childMap, remainingParts.drop(1), note, fullRelPath)
        map[nodePath] = folder.copy(
            children = childMap.values.sortedWith(compareBy({ it !is NoteTreeNode.Folder }, { it.name.lowercase() }))
        )
    }
}

/** 把节点列表转成以 path 为 key 的 MutableMap，便于插入子节点 */
private fun List<NoteTreeNode>.toMutableMapByPath(): MutableMap<String, NoteTreeNode> =
    this.associateBy { it.path }.toMutableMap()
