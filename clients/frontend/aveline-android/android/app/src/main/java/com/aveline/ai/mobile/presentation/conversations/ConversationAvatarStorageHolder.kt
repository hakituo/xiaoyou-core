package com.aveline.ai.mobile.presentation.conversations

import androidx.lifecycle.ViewModel
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

/**
 * ConversationList 页面头像存储持有者。
 *
 * 把 PersonaAvatarStorage（@Singleton）暴露给 ConversationListScreen / PersonaEditSheet
 * 用于加载本地图片。如果直接给 Screen 传 Singleton Bean，Compose 会拿不到，
 * 所以借 ViewModel 转发一次。
 */
@HiltViewModel
class ConversationAvatarStorageHolder @Inject constructor(
    val avatarStorage: PersonaAvatarStorage
) : ViewModel()
