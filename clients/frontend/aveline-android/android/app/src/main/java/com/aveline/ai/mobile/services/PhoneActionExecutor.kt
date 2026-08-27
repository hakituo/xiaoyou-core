package com.aveline.ai.mobile.services

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.AlarmClock
import android.provider.CalendarContract
import android.provider.Settings
import android.telephony.SmsManager
import android.util.Log
import com.aveline.ai.mobile.domain.models.PhoneAction
import com.aveline.ai.mobile.domain.models.PhoneActionResult
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.JsonPrimitive
import java.util.TimeZone
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume

@Singleton
class PhoneActionExecutor @Inject constructor(
    @ApplicationContext private val context: Context,
    private val fusedLocationClient: FusedLocationProviderClient
) {
    companion object {
        private const val TAG = "PhoneActionExecutor"
    }

    // 媒体与音量动作执行器
    private val mediaActionExecutor = MediaActionExecutor(context)

    // 通知相关动作执行器
    private val notificationActionExecutor = NotificationActionExecutor(context)

    suspend fun execute(action: PhoneAction): PhoneActionResult {
        Log.i(TAG, "执行手机操作: ${action::class.simpleName}")
        return try {
            when (action) {
                is PhoneAction.CreateCalendarEvent -> createCalendarEvent(action)
                is PhoneAction.SetAlarm -> setAlarm(action)
                is PhoneAction.SetTimer -> setTimer(action)
                is PhoneAction.OpenApp -> openApp(action)
                is PhoneAction.MakePhoneCall -> makePhoneCall(action)
                is PhoneAction.SendSms -> sendSms(action)
                is PhoneAction.OpenNavigation -> openNavigation(action)
                is PhoneAction.SetDndMode -> notificationActionExecutor.setDndMode(action)
                is PhoneAction.MediaControl -> mediaActionExecutor.mediaControl(action)
                is PhoneAction.OpenSettings -> openSettings(action)
                is PhoneAction.ShareContent -> shareContent(action)
                is PhoneAction.SetVolume -> mediaActionExecutor.setVolume(action)
                is PhoneAction.GetLocation -> getLocation(action)
                is PhoneAction.Unknown -> PhoneActionResult(
                    actionId = action.actionId,
                    success = false,
                    resultType = "unknown",
                    error = "未知操作类型: ${action.rawType}"
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "操作执行失败: ${action::class.simpleName}", e)
            PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "error",
                error = e.message ?: "未知错误"
            )
        }
    }

    private fun createCalendarEvent(action: PhoneAction.CreateCalendarEvent): PhoneActionResult {
        if (!hasPermission(Manifest.permission.WRITE_CALENDAR)) {
            return PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "permission_denied",
                error = "缺少日历写入权限"
            )
        }

        val values = android.content.ContentValues().apply {
            put(CalendarContract.Events.DTSTART, action.startTime)
            put(CalendarContract.Events.DTEND, action.endTime)
            put(CalendarContract.Events.TITLE, action.title)
            put(CalendarContract.Events.DESCRIPTION, action.description)
            put(CalendarContract.Events.CALENDAR_ID, getDefaultCalendarId())
            put(CalendarContract.Events.EVENT_TIMEZONE, TimeZone.getDefault().id)
            if (action.allDay) {
                put(CalendarContract.Events.ALL_DAY, 1)
            }
        }

        val uri = context.contentResolver.insert(CalendarContract.Events.CONTENT_URI, values)
            ?: return PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "insert_failed",
                error = "日历事件插入失败"
            )

        val eventId = uri.lastPathSegment?.toLongOrNull() ?: 0L

        if (action.reminderMinutes > 0 && eventId > 0) {
            val reminderValues = android.content.ContentValues().apply {
                put(CalendarContract.Reminders.EVENT_ID, eventId)
                put(CalendarContract.Reminders.MINUTES, action.reminderMinutes)
                put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT)
            }
            context.contentResolver.insert(CalendarContract.Reminders.CONTENT_URI, reminderValues)
        }

        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "calendar_event_created",
            data = mapOf("eventId" to JsonPrimitive(eventId))
        )
    }

    private fun getDefaultCalendarId(): Long {
        val projection = arrayOf(
            CalendarContract.Calendars._ID,
            CalendarContract.Calendars.IS_PRIMARY
        )
        val uri = CalendarContract.Calendars.CONTENT_URI.buildUpon()
            .appendQueryParameter(CalendarContract.CALLER_IS_SYNCADAPTER, "true")
            .appendQueryParameter(CalendarContract.Calendars.ACCOUNT_TYPE, "com.google")
            .build()

        var calendarId = 1L
        context.contentResolver.query(uri, projection, null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) {
                val idIdx = cursor.getColumnIndex(CalendarContract.Calendars._ID)
                val primaryIdx = cursor.getColumnIndex(CalendarContract.Calendars.IS_PRIMARY)
                if (idIdx >= 0) {
                    val id = cursor.getLong(idIdx)
                    if (primaryIdx >= 0 && cursor.getString(primaryIdx) == "1") {
                        calendarId = id
                        break
                    }
                    calendarId = id
                }
            }
        }
        return calendarId
    }

    private fun setAlarm(action: PhoneAction.SetAlarm): PhoneActionResult {
        val alarmIntent = Intent(AlarmClock.ACTION_SET_ALARM).apply {
            putExtra(AlarmClock.EXTRA_HOUR, action.hour)
            putExtra(AlarmClock.EXTRA_MINUTES, action.minute)
            putExtra(AlarmClock.EXTRA_MESSAGE, action.message)
            putExtra(AlarmClock.EXTRA_VIBRATE, action.vibrate)
            if (action.skipUi) {
                putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            }
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        return if (alarmIntent.resolveActivity(context.packageManager) != null) {
            context.startActivity(alarmIntent)
            PhoneActionResult(
                actionId = action.actionId,
                success = true,
                resultType = "alarm_set",
                data = mapOf(
                    "hour" to JsonPrimitive(action.hour),
                    "minute" to JsonPrimitive(action.minute)
                )
            )
        } else {
            PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "no_alarm_app",
                error = "设备没有闹钟应用"
            )
        }
    }

    private fun setTimer(action: PhoneAction.SetTimer): PhoneActionResult {
        val timerIntent = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, action.seconds)
            putExtra(AlarmClock.EXTRA_MESSAGE, action.message)
            if (action.skipUi) {
                putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            }
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        return if (timerIntent.resolveActivity(context.packageManager) != null) {
            context.startActivity(timerIntent)
            PhoneActionResult(
                actionId = action.actionId,
                success = true,
                resultType = "timer_set",
                data = mapOf("seconds" to JsonPrimitive(action.seconds))
            )
        } else {
            PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "no_timer_app",
                error = "设备没有定时器应用"
            )
        }
    }

    private fun openApp(action: PhoneAction.OpenApp): PhoneActionResult {
        val launchIntent = context.packageManager.getLaunchIntentForPackage(action.packageName)

        return if (launchIntent != null) {
            launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (action.query.isNotEmpty()) {
                launchIntent.putExtra("query", action.query)
            }
            context.startActivity(launchIntent)
            val appName = getAppName(action.packageName)
            PhoneActionResult(
                actionId = action.actionId,
                success = true,
                resultType = "app_opened",
                data = mapOf(
                    "packageName" to JsonPrimitive(action.packageName),
                    "appName" to JsonPrimitive(appName)
                )
            )
        } else {
            PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "app_not_found",
                error = "未找到应用: ${action.packageName}"
            )
        }
    }

    private fun makePhoneCall(action: PhoneAction.MakePhoneCall): PhoneActionResult {
        if (!hasPermission(Manifest.permission.CALL_PHONE)) {
            val dialIntent = Intent(Intent.ACTION_DIAL).apply {
                data = Uri.parse("tel:${action.phoneNumber}")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(dialIntent)
            return PhoneActionResult(
                actionId = action.actionId,
                success = true,
                resultType = "dial_only",
                data = mapOf("phoneNumber" to JsonPrimitive(action.phoneNumber)),
                error = "缺少拨号权限，已打开拨号界面"
            )
        }

        val callIntent = Intent(Intent.ACTION_CALL).apply {
            data = Uri.parse("tel:${action.phoneNumber}")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(callIntent)
        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "call_initiated",
            data = mapOf("phoneNumber" to JsonPrimitive(action.phoneNumber))
        )
    }

    private fun sendSms(action: PhoneAction.SendSms): PhoneActionResult {
        if (!hasPermission(Manifest.permission.SEND_SMS)) {
            val smsIntent = Intent(Intent.ACTION_SENDTO).apply {
                data = Uri.parse("smsto:${action.phoneNumber}")
                putExtra("sms_body", action.message)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(smsIntent)
            return PhoneActionResult(
                actionId = action.actionId,
                success = true,
                resultType = "sms_draft_only",
                data = mapOf("phoneNumber" to JsonPrimitive(action.phoneNumber)),
                error = "缺少短信权限，已打开短信编辑界面"
            )
        }

        val smsManager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            context.getSystemService(SmsManager::class.java)
        } else {
            @Suppress("DEPRECATION")
            SmsManager.getDefault()
        }
        smsManager.sendTextMessage(action.phoneNumber, null, action.message, null, null)
        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "sms_sent",
            data = mapOf(
                "phoneNumber" to JsonPrimitive(action.phoneNumber),
                "messageLength" to JsonPrimitive(action.message.length)
            )
        )
    }

    private fun openNavigation(action: PhoneAction.OpenNavigation): PhoneActionResult {
        val modeParam = when (action.mode) {
            "walking" -> "w"
            "bicycling" -> "b"
            "transit" -> "r"
            else -> "d"
        }
        val uri = Uri.parse("google.navigation:q=${Uri.encode(action.destination)}&mode=$modeParam")
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            setPackage("com.google.android.apps.maps")
        }

        return if (intent.resolveActivity(context.packageManager) != null) {
            context.startActivity(intent)
            PhoneActionResult(
                actionId = action.actionId,
                success = true,
                resultType = "navigation_started",
                data = mapOf(
                    "destination" to JsonPrimitive(action.destination),
                    "mode" to JsonPrimitive(action.mode)
                )
            )
        } else {
            val fallbackUri = Uri.parse("https://maps.google.com/maps?daddr=${Uri.encode(action.destination)}&dirflg=$modeParam")
            val fallbackIntent = Intent(Intent.ACTION_VIEW, fallbackUri).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(fallbackIntent)
            PhoneActionResult(
                actionId = action.actionId,
                success = true,
                resultType = "navigation_browser",
                data = mapOf("destination" to JsonPrimitive(action.destination)),
                error = "未安装谷歌地图，已用浏览器打开"
            )
        }
    }

    private fun openSettings(action: PhoneAction.OpenSettings): PhoneActionResult {
        val intent = when (action.settingsType) {
            "wifi" -> Settings.ACTION_WIFI_SETTINGS
            "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
            "location" -> Settings.ACTION_LOCATION_SOURCE_SETTINGS
            "display" -> Settings.ACTION_DISPLAY_SETTINGS
            "sound" -> Settings.ACTION_SOUND_SETTINGS
            "storage" -> Settings.ACTION_INTERNAL_STORAGE_SETTINGS
            "about" -> Settings.ACTION_DEVICE_INFO_SETTINGS
            "app" -> Settings.ACTION_APPLICATION_SETTINGS
            "accessibility" -> Settings.ACTION_ACCESSIBILITY_SETTINGS
            "security" -> Settings.ACTION_SECURITY_SETTINGS
            "data_usage" -> Settings.ACTION_DATA_USAGE_SETTINGS
            "nfc" -> Settings.ACTION_NFC_SETTINGS
            "battery" -> Settings.ACTION_BATTERY_SAVER_SETTINGS
            else -> Settings.ACTION_SETTINGS
        }

        val settingsIntent = Intent(intent).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(settingsIntent)

        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "settings_opened",
            data = mapOf("settingsType" to JsonPrimitive(action.settingsType))
        )
    }

    private fun shareContent(action: PhoneAction.ShareContent): PhoneActionResult {
        val sendIntent = Intent().apply {
            setAction(Intent.ACTION_SEND)
            putExtra(Intent.EXTRA_TEXT, action.text)
            if (action.title.isNotEmpty()) {
                putExtra(Intent.EXTRA_SUBJECT, action.title)
            }
            type = "text/plain"
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val chooserIntent = Intent.createChooser(sendIntent, action.title.ifEmpty { "分享" }).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(chooserIntent)

        return PhoneActionResult(
            actionId = action.actionId,
            success = true,
            resultType = "share_dialog_opened"
        )
    }

    private suspend fun getLocation(action: PhoneAction.GetLocation): PhoneActionResult {
        if (!hasPermission(Manifest.permission.ACCESS_FINE_LOCATION) &&
            !hasPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
        ) {
            return PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "permission_denied",
                error = "缺少位置权限"
            )
        }

        return try {
            val location = suspendCancellableCoroutine { cont ->
                val cts = CancellationTokenSource()
                fusedLocationClient.getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, cts.token)
                    .addOnSuccessListener { loc -> cont.resume(loc) }
                    .addOnFailureListener { _ -> cont.resume(null) }
                cont.invokeOnCancellation { cts.cancel() }
            }

            if (location != null) {
                PhoneActionResult(
                    actionId = action.actionId,
                    success = true,
                    resultType = "location",
                    data = mapOf(
                        "latitude" to JsonPrimitive(location.latitude),
                        "longitude" to JsonPrimitive(location.longitude),
                        "accuracy" to JsonPrimitive(location.accuracy.toDouble()),
                        "timestamp" to JsonPrimitive(location.time)
                    )
                )
            } else {
                PhoneActionResult(
                    actionId = action.actionId,
                    success = false,
                    resultType = "location_unavailable",
                    error = "无法获取位置信息"
                )
            }
        } catch (e: Exception) {
            PhoneActionResult(
                actionId = action.actionId,
                success = false,
                resultType = "location_error",
                error = e.message ?: "位置获取失败"
            )
        }
    }

    private fun hasPermission(permission: String): Boolean {
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
    }

    private fun getAppName(packageName: String): String {
        return try {
            val appInfo = context.packageManager.getApplicationInfo(packageName, 0)
            context.packageManager.getApplicationLabel(appInfo).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            packageName.substringAfterLast(".")
        }
    }
}
