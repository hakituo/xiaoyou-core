package com.aveline.ai.mobile.presentation.memory

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.*
import com.aveline.ai.mobile.domain.repository.MemoryRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

/**
 * 记忆管理 UI 状态
 * 
 * @property memories 记忆列表
 * @property searchQuery 搜索关键词
 * @property selectedType 选中的类型过滤
 * @property sortOrder 排序方式
 * @property stats 记忆统计
 * @property isLoading 是否加载中
 * @property error 错误信息
 * @property showDeleteConfirm 是否显示删除确认
 * @property memoryToDelete 待删除的记忆
 * @property showMemoryDetail 是否显示记忆详情弹窗
 * @property selectedMemory 当前正在查看详情的记忆
 */
data class MemoryUiState(
    val memories: List<Memory> = emptyList(),
    val searchQuery: String = "",
    val selectedType: MemoryType? = null,
    val sortOrder: MemorySortOrder = MemorySortOrder.NEWEST_FIRST,
    val stats: MemoryStats? = null,
    val isLoading: Boolean = false,
    val error: String? = null,
    val showDeleteConfirm: Boolean = false,
    val memoryToDelete: Memory? = null,
    val showImportantOnly: Boolean = false,
    val availableTags: List<String> = emptyList(),
    val showMemoryDetail: Boolean = false,
    val selectedMemory: Memory? = null
) {
    val filteredMemories: List<Memory>
        get() {
            var result = memories
            
            if (selectedType != null) {
                result = result.filter { it.type == selectedType }
            }
            
            if (showImportantOnly) {
                result = result.filter { it.isImportant }
            }
            
            if (searchQuery.isNotBlank()) {
                result = result.filter { 
                    it.content.contains(searchQuery, ignoreCase = true) ||
                    it.tags.any { tag -> tag.contains(searchQuery, ignoreCase = true) }
                }
            }
            
            return when (sortOrder) {
                MemorySortOrder.NEWEST_FIRST -> result.sortedByDescending { it.createdAt }
                MemorySortOrder.OLDEST_FIRST -> result.sortedBy { it.createdAt }
                MemorySortOrder.MOST_ACCESSED -> result.sortedByDescending { it.accessCount }
                MemorySortOrder.MOST_IMPORTANT -> result.sortedByDescending { it.importance }
            }
        }
    
    val hasMemories: Boolean
        get() = memories.isNotEmpty()
    
    val hasFilters: Boolean
        get() = selectedType != null || showImportantOnly || searchQuery.isNotBlank()
}

/**
 * 记忆管理 ViewModel
 * 
 * 功能：
 * - 记忆列表加载和刷新
 * - 搜索和过滤
 * - 删除和标记重要
 * 
 * Requirements: 9.1, 9.2, 9.3
 */
@HiltViewModel
class MemoryViewModel @Inject constructor(
    private val memoryRepository: MemoryRepository
) : ViewModel() {

    private companion object {
        const val TAG = "MemoryViewModel"
    }

    private val _uiState = MutableStateFlow(MemoryUiState())
    val uiState: StateFlow<MemoryUiState> = _uiState.asStateFlow()

    private var searchJob: Job? = null
    private val searchDebounceMs = 300L

    /** 当前正在查看的 persona 文件名（来自聊天会话/伴侣面板选择，纯只读）；为 null 表示用后端默认 */
    @Volatile
    private var currentPersonaFilename: String? = null

    init {
        // 初始先用 null 加载一次（后端默认），随后由 ChatScreen 通过 setViewingPersona 注入
        // 当前聊天对应的角色文件名，再按角色重新加载。
        viewModelScope.launch(Dispatchers.IO) {
            loadMemories()
            loadStats()
            loadTags()
        }
    }

    /**
     * 设置“正在查看的角色”对应的 persona 文件名（纯只读查询，不切对话人设）。
     * 由 ChatScreen 在聊天进入 / 面板内选版本时调用。
     */
    fun setViewingPersona(filename: String) {
        if (filename.isBlank() || filename == currentPersonaFilename) return
        currentPersonaFilename = filename
        Log.d(TAG, "查看角色 persona 文件名: $filename")
        viewModelScope.launch(Dispatchers.IO) {
            loadMemories()
            loadStats()
            loadTags()
        }
    }

    /**
     * 加载记忆列表
     */
    fun loadMemories() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }

            val filter = MemoryFilter(
                types = _uiState.value.selectedType?.let { setOf(it) } ?: emptySet(),
                showImportantOnly = _uiState.value.showImportantOnly
            )

            val result = memoryRepository.getMemories(
                filter,
                _uiState.value.sortOrder,
                persona = currentPersonaFilename
            )

            _uiState.update {
                it.copy(
                    memories = result,
                    isLoading = false
                )
            }
        }
    }

    /**
     * 加载统计信息
     */
    private fun loadStats() {
        viewModelScope.launch {
            val stats = memoryRepository.getMemoryStats(persona = currentPersonaFilename)
            _uiState.update { it.copy(stats = stats) }
        }
    }

    /**
     * 加载标签列表
     */
    private fun loadTags() {
        viewModelScope.launch {
            val tags = memoryRepository.getTags(persona = currentPersonaFilename)
            _uiState.update { it.copy(availableTags = tags) }
        }
    }
    
    /**
     * 搜索记忆（带防抖）
     */
    fun search(query: String) {
        _uiState.update { it.copy(searchQuery = query) }
        
        searchJob?.cancel()
        
        if (query.isBlank()) {
            loadMemories()
            return
        }
        
        searchJob = viewModelScope.launch {
            delay(searchDebounceMs)
            
            _uiState.update { it.copy(isLoading = true) }
            
            val results = memoryRepository.searchMemories(query, persona = currentPersonaFilename)
            
            _uiState.update { 
                it.copy(
                    memories = results,
                    isLoading = false
                )
            }
        }
    }
    
    /**
     * 设置类型过滤
     */
    fun setTypeFilter(type: MemoryType?) {
        _uiState.update { it.copy(selectedType = type) }
        loadMemories()
    }
    
    /**
     * 切换只显示重要
     */
    fun toggleImportantOnly() {
        _uiState.update { it.copy(showImportantOnly = !it.showImportantOnly) }
        loadMemories()
    }
    
    /**
     * 设置排序方式
     */
    fun setSortOrder(order: MemorySortOrder) {
        _uiState.update { it.copy(sortOrder = order) }
    }
    
    /**
     * 删除记忆
     */
    fun deleteMemory(memory: Memory) {
        _uiState.update { 
            it.copy(
                showDeleteConfirm = true,
                memoryToDelete = memory
            )
        }
    }
    
    /**
     * 确认删除
     */
    fun confirmDelete() {
        val memory = _uiState.value.memoryToDelete ?: return
        
        viewModelScope.launch {
            val result = memoryRepository.deleteMemory(memory.id)
            
            result.fold(
                onSuccess = {
                    _uiState.update { 
                        it.copy(
                            memories = it.memories.filter { m -> m.id != memory.id },
                            showDeleteConfirm = false,
                            memoryToDelete = null
                        )
                    }
                    loadStats()
                },
                onFailure = { e ->
                    _uiState.update { 
                        it.copy(
                            error = "删除失败: ${e.message}",
                            showDeleteConfirm = false,
                            memoryToDelete = null
                        )
                    }
                }
            )
        }
    }
    
    /**
     * 取消删除
     */
    fun cancelDelete() {
        _uiState.update { 
            it.copy(
                showDeleteConfirm = false,
                memoryToDelete = null
            )
        }
    }

    /**
     * 打开记忆详情弹窗
     */
    fun openMemoryDetail(memory: Memory) {
        _uiState.update { it.copy(showMemoryDetail = true, selectedMemory = memory) }
    }

    /**
     * 关闭记忆详情弹窗
     */
    fun closeMemoryDetail() {
        _uiState.update { it.copy(showMemoryDetail = false, selectedMemory = null) }
    }
    
    /**
     * 切换重要标记
     */
    fun toggleImportant(memory: Memory) {
        viewModelScope.launch {
            val result = memoryRepository.markImportant(memory.id, !memory.isImportant)
            
            result.fold(
                onSuccess = {
                    _uiState.update { state ->
                        state.copy(
                            memories = state.memories.map { m ->
                                if (m.id == memory.id) {
                                    m.copy(isImportant = !m.isImportant)
                                } else m
                            }
                        )
                    }
                    loadStats()
                },
                onFailure = { e ->
                    _uiState.update { it.copy(error = "操作失败: ${e.message}") }
                }
            )
        }
    }
    
    /**
     * 清除错误
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
    
    /**
     * 清除过滤
     */
    fun clearFilters() {
        _uiState.update { 
            it.copy(
                searchQuery = "",
                selectedType = null,
                showImportantOnly = false
            )
        }
        loadMemories()
    }
}
