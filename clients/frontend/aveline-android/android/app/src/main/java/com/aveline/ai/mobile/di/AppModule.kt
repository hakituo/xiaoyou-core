package com.aveline.ai.mobile.di

import android.app.Application
import android.content.Context
import android.content.res.Resources
import com.aveline.ai.mobile.data.wear.WearDataSource
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationServices
import com.samsung.android.sdk.health.data.HealthDataService
import com.samsung.android.sdk.health.data.HealthDataStore
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideApplicationContext(application: Application): Context {
        return application.applicationContext
    }

    @Provides
    @Singleton
    fun provideResources(@ApplicationContext context: Context): Resources {
        return context.resources
    }

    @Provides
    @Singleton
    fun provideFusedLocationProviderClient(@ApplicationContext context: Context): FusedLocationProviderClient {
        return LocationServices.getFusedLocationProviderClient(context)
    }

    @Provides
    @Singleton
    fun provideWearDataSource(@ApplicationContext context: Context): WearDataSource {
        return WearDataSource(context)
    }

    // Samsung Health Data SDK 的 store 无需显式 connect, 首次 suspend 调用时才懒绑定平台;
    // 这里做单例绑定, 保证多个健康数据读取器共用同一份 store 实例。
    @Provides
    @Singleton
    fun provideSamsungHealthDataStore(@ApplicationContext context: Context): HealthDataStore {
        return HealthDataService.getStore(context)
    }
}
