package com.aveline.ai.mobile.presentation.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject

/**
 * ChatScreen 顶部栏头像数据持有者。
 *
 * 把 PersonaAvatarStorage（@Singleton）+ persona_filename -> avatarPath 的映射
 * 暴露给 ChatScreen，避免 ChatScreen 直接构造/依赖数据层。
 */
@HiltViewModel
class ChatAvatarStorageHolder @Inject constructor(
    val avatarStorage: PersonaAvatarStorage,
    personaLocalMetaRepository: PersonaLocalMetaRepository
) : ViewModel() {

    /** 本地 persona 元数据仓库（昵称/头像自定义），供伴侣详情页编辑资料使用。 */
    val localMeta: PersonaLocalMetaRepository = personaLocalMetaRepository

    /**
     * persona_filename -> avatarPath 映射（本地自定义头像）。
     * 用于 ChatScreen 顶部头像渲染：找到当前激活 persona 对应的本地头像文件名。
     */
    val localAvatarMap: StateFlow<Map<String, String>> =
        personaLocalMetaRepository.observeAll()
            .map { list ->
                list.mapNotNull { entity ->
                    entity.avatarPath?.let { entity.personaFilename to it }
                }.toMap()
            }
            .stateIn(
                scope = viewModelScope,
                started = SharingStarted.WhileSubscribed(5000),
                initialValue = emptyMap()
            )
}
