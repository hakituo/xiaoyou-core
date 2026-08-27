package com.aveline.ai.mobile.services

import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import javax.inject.Inject

@AndroidEntryPoint
class AvelineFirebaseMessagingService : FirebaseMessagingService() {

    @Inject
    lateinit var appPreferences: AppPreferences

    @Inject
    lateinit var apiService: AvelineApiService

    @Inject
    lateinit var notificationManager: AvelineNotificationManager

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        notificationManager.createNotificationChannels()
        refreshAndUploadToken()
    }

    override fun onDestroy() {
        serviceScope.cancel()
        super.onDestroy()
    }

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        serviceScope.launch {
            uploadToken(token)
        }
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)

        val title = remoteMessage.notification?.title
            ?: remoteMessage.data["title"]
            ?: "Aveline"

        val body = remoteMessage.notification?.body
            ?: remoteMessage.data["body"]
            ?: remoteMessage.data["message"]
            ?: "收到一条新消息"

        val sessionId = remoteMessage.data["session_id"]
        notificationManager.showMessageNotification(
            title = title,
            message = body,
            sessionId = sessionId
        )
    }

    private fun refreshAndUploadToken() {
        FirebaseMessaging.getInstance().token
            .addOnSuccessListener { token ->
                if (!token.isNullOrBlank()) {
                    serviceScope.launch {
                        uploadToken(token)
                    }
                }
            }
            .addOnFailureListener { error ->
                Log.w(TAG, "Failed to fetch FCM token: ${error.message}")
            }
    }

    private suspend fun uploadToken(token: String) {
        val payload = buildJsonObject {
            put("token", token)
            put("platform", "android")
            put("user_id", appPreferences.userId)
            put("user_name", appPreferences.userName)
        }

        runCatching {
            apiService.registerMobilePushToken(payload)
        }.onFailure { error ->
            Log.w(TAG, "Failed to upload FCM token: ${error.message}")
        }
    }

    companion object {
        private const val TAG = "AvelineFCM"
    }
}
