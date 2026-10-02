package com.aveline.ai.mobile.di

import com.aveline.ai.mobile.presentation.assistant.ports.AssistantActionPort
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantBackendPort
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantSpeechPort
import com.aveline.ai.mobile.presentation.assistant.ports.AssistantWakeWordPort
import com.aveline.ai.mobile.presentation.assistant.ports.StubAssistantActionPort
import com.aveline.ai.mobile.presentation.assistant.ports.StubAssistantBackendPort
import com.aveline.ai.mobile.presentation.assistant.ports.StubAssistantSpeechPort
import com.aveline.ai.mobile.presentation.assistant.ports.StubAssistantWakeWordPort
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * 语音助手端口的 Hilt 绑定。
 *
 * **接后端时唯一需要改的地方**：把某个 `@Binds` 的右侧实现换成真实实现类即可，
 * 例如把 `StubAssistantBackendPort` 换成 `HttpAssistantBackendPort`，
 * UI / ViewModel / 动画全都感知不到这次替换。
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class AssistantPortsModule {

    @Binds
    @Singleton
    abstract fun bindAssistantBackendPort(
        impl: StubAssistantBackendPort
    ): AssistantBackendPort

    @Binds
    @Singleton
    abstract fun bindAssistantSpeechPort(
        impl: StubAssistantSpeechPort
    ): AssistantSpeechPort

    @Binds
    @Singleton
    abstract fun bindAssistantActionPort(
        impl: StubAssistantActionPort
    ): AssistantActionPort

    @Binds
    @Singleton
    abstract fun bindAssistantWakeWordPort(
        impl: StubAssistantWakeWordPort
    ): AssistantWakeWordPort
}
