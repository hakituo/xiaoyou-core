package com.aveline.ai.mobile.di

import android.content.Context
import androidx.room.Room
import com.aveline.ai.mobile.data.local.database.AvelineDatabase
import com.aveline.ai.mobile.data.local.database.dao.MemoryDao
import com.aveline.ai.mobile.data.local.database.dao.MessageDao
import com.aveline.ai.mobile.data.local.database.dao.SessionDao
import com.aveline.ai.mobile.data.local.database.dao.HealthDataDao
import com.aveline.ai.mobile.data.local.database.dao.NotificationDao
import com.aveline.ai.mobile.data.local.database.dao.PersonaLocalMetaDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideAvelineDatabase(@ApplicationContext context: Context): AvelineDatabase {
        return Room.databaseBuilder(
            context,
            AvelineDatabase::class.java,
            AvelineDatabase.DATABASE_NAME
        )
            // v1 -> v2: 仅新增 persona_local_meta 表，不影响旧数据
            // v2 -> v3: persona_local_meta 加 lastMessagePreview / lastMessageAt 两列
            .addMigrations(
                AvelineDatabase.MIGRATION_1_2,
                AvelineDatabase.MIGRATION_2_3,
                AvelineDatabase.MIGRATION_3_4
            )
            // 仅在降级时允许销毁数据;升级时必须编写正式 Migration,防止用户数据丢失
            .fallbackToDestructiveMigrationOnDowngrade()
            .build()
    }

    @Provides
    fun provideMessageDao(database: AvelineDatabase): MessageDao {
        return database.messageDao()
    }

    @Provides
    fun provideSessionDao(database: AvelineDatabase): SessionDao {
        return database.sessionDao()
    }

    @Provides
    fun provideMemoryDao(database: AvelineDatabase): MemoryDao {
        return database.memoryDao()
    }

    @Provides
    fun provideNotificationDao(database: AvelineDatabase): NotificationDao {
        return database.notificationDao()
    }

    @Provides
    fun provideHealthDataDao(database: AvelineDatabase): HealthDataDao {
        return database.healthDataDao()
    }

    @Provides
    fun providePersonaLocalMetaDao(database: AvelineDatabase): PersonaLocalMetaDao {
        return database.personaLocalMetaDao()
    }
}
