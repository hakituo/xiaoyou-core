package com.aveline.ai.mobile.di

import com.aveline.ai.mobile.data.repository.ChatRepositoryImpl
import com.aveline.ai.mobile.data.repository.ContextRepositoryImpl
import com.aveline.ai.mobile.data.repository.HealthRepositoryImpl
import com.aveline.ai.mobile.data.repository.MemoryRepositoryImpl
import com.aveline.ai.mobile.data.repository.PersonaRepositoryImpl
import com.aveline.ai.mobile.data.repository.PluginsRepositoryImpl
import com.aveline.ai.mobile.data.repository.SessionRepositoryImpl
import com.aveline.ai.mobile.data.repository.ShopRepositoryImpl
import com.aveline.ai.mobile.data.repository.StatusRepositoryImpl
import com.aveline.ai.mobile.data.repository.StudyRepositoryImpl
import com.aveline.ai.mobile.data.repository.ToolsRepositoryImpl
import com.aveline.ai.mobile.data.repository.WellbeingRepositoryImpl
import com.aveline.ai.mobile.domain.repository.ChatRepository
import com.aveline.ai.mobile.domain.repository.ContextRepository
import com.aveline.ai.mobile.domain.repository.HealthRepository
import com.aveline.ai.mobile.domain.repository.MemoryRepository
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.PluginsRepository
import com.aveline.ai.mobile.domain.repository.SessionRepository
import com.aveline.ai.mobile.domain.repository.ShopRepository
import com.aveline.ai.mobile.domain.repository.StatusRepository
import com.aveline.ai.mobile.domain.repository.StudyRepository
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import com.aveline.ai.mobile.domain.repository.WellbeingRepository
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Hilt module for repository bindings.
 * 
 * This module binds repository interfaces to their implementations,
 * allowing Hilt to inject the correct implementation when a repository
 * interface is requested.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {
    
    /**
     * Binds ChatRepository interface to ChatRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindChatRepository(
        chatRepositoryImpl: ChatRepositoryImpl
    ): ChatRepository
    
    /**
     * Binds SessionRepository interface to SessionRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindSessionRepository(
        sessionRepositoryImpl: SessionRepositoryImpl
    ): SessionRepository
    
    /**
     * Binds StatusRepository interface to StatusRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindStatusRepository(
        statusRepositoryImpl: StatusRepositoryImpl
    ): StatusRepository
    
    /**
     * Binds HealthRepository interface to HealthRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindHealthRepository(
        healthRepositoryImpl: HealthRepositoryImpl
    ): HealthRepository
    
    /**
     * Binds ContextRepository interface to ContextRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindContextRepository(
        contextRepositoryImpl: ContextRepositoryImpl
    ): ContextRepository
    
    /**
     * Binds MemoryRepository interface to MemoryRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindMemoryRepository(
        memoryRepositoryImpl: MemoryRepositoryImpl
    ): MemoryRepository
    
    /**
     * Binds StudyRepository interface to StudyRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindStudyRepository(
        studyRepositoryImpl: StudyRepositoryImpl
    ): StudyRepository
    
    /**
     * Binds PersonaRepository interface to PersonaRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindPersonaRepository(
        personaRepositoryImpl: PersonaRepositoryImpl
    ): PersonaRepository
    
    /**
     * Binds PluginsRepository interface to PluginsRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindPluginsRepository(
        pluginsRepositoryImpl: PluginsRepositoryImpl
    ): PluginsRepository
    
    /**
     * Binds ShopRepository interface to ShopRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindShopRepository(
        shopRepositoryImpl: ShopRepositoryImpl
    ): ShopRepository

    @Binds
    @Singleton
    abstract fun bindToolsRepository(
        toolsRepositoryImpl: ToolsRepositoryImpl
    ): ToolsRepository

    /**
     * Binds WellbeingRepository interface to WellbeingRepositoryImpl.
     */
    @Binds
    @Singleton
    abstract fun bindWellbeingRepository(
        wellbeingRepositoryImpl: WellbeingRepositoryImpl
    ): WellbeingRepository
}
