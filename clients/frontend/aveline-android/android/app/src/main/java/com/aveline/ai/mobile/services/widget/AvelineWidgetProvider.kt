package com.aveline.ai.mobile.services.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import android.widget.Toast
import com.aveline.ai.R
import com.aveline.ai.mobile.presentation.MainActivity
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Aveline 组合小组件 Provider
 *
 * 显示内容：
 * 1. AI 状态（情绪 + 生命状态条）
 * 2. 最近消息
 * 3. 快速输入
 */
class AvelineWidgetProvider : AppWidgetProvider() {

    companion object {
        const val ACTION_QUICK_SEND = "com.aveline.ai.ACTION_WIDGET_QUICK_SEND"
        const val ACTION_REFRESH = "com.aveline.ai.ACTION_WIDGET_REFRESH"
        const val EXTRA_MESSAGE = "extra_message"

        /**
         * 更新所有 Widget 实例
         */
        fun updateAllWidgets(context: Context) {
            val intent = Intent(context, AvelineWidgetProvider::class.java).apply {
                action = AppWidgetManager.ACTION_APPWIDGET_UPDATE
            }
            val appWidgetManager = AppWidgetManager.getInstance(context)
            val componentName = ComponentName(context, AvelineWidgetProvider::class.java)
            val widgetIds = appWidgetManager.getAppWidgetIds(componentName)
            intent.putExtra(AppWidgetManager.EXTRA_APPWIDGET_IDS, widgetIds)
            context.sendBroadcast(intent)
        }
    }

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray
    ) {
        for (appWidgetId in appWidgetIds) {
            updateAppWidget(context, appWidgetManager, appWidgetId)
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)

        when (intent.action) {
            ACTION_QUICK_SEND -> {
                val message = intent.getStringExtra(EXTRA_MESSAGE) ?: ""
                if (message.isNotBlank()) {
                    // 发送消息到主应用
                    sendQuickMessage(context, message)
                }
            }
            ACTION_REFRESH -> {
                // 刷新 Widget 数据
                updateAllWidgets(context)
            }
        }
    }

    override fun onEnabled(context: Context) {
        // 第一个 Widget 被添加时调用
        super.onEnabled(context)
        // 启动后台更新服务
        AvelineWidgetWorker.start(context)
    }

    override fun onDisabled(context: Context) {
        // 最后一个 Widget 被移除时调用
        super.onDisabled(context)
        // 停止后台更新服务
        AvelineWidgetWorker.stop(context)
    }

    private fun updateAppWidget(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetId: Int
    ) {
        val views = RemoteViews(context.packageName, R.layout.widget_aveline)

        // 读取 Widget 数据
        val prefs = context.getSharedPreferences("widget_data", Context.MODE_PRIVATE)
        val widgetData = WidgetData.fromPreferences(prefs)

        // 更新 AI 名称和情绪
        views.setTextViewText(R.id.widget_ai_name, widgetData.aiName)
        views.setTextViewText(R.id.widget_emotion_text, widgetData.emotionText)
        views.setImageViewResource(R.id.widget_emotion_icon, getEmotionIconRes())

        // 更新生命状态条
        views.setProgressBar(R.id.widget_health_bar, 100, (widgetData.health * 100).toInt(), false)
        views.setProgressBar(R.id.widget_happiness_bar, 100, (widgetData.happiness * 100).toInt(), false)
        views.setProgressBar(R.id.widget_energy_bar, 100, (widgetData.energy * 100).toInt(), false)
        views.setProgressBar(R.id.widget_hunger_bar, 100, (widgetData.hunger * 100).toInt(), false)

        // 更新连接状态
        views.setInt(
            R.id.widget_connection_status,
            "setBackgroundColor",
            if (widgetData.isConnected) 0xFF4CAF50.toInt() else 0xFFF44336.toInt()
        )

        // 更新最近消息
        if (widgetData.lastMessage.isNotBlank()) {
            views.setTextViewText(R.id.widget_last_message, widgetData.lastMessage)
            views.setTextViewText(R.id.widget_message_time, widgetData.lastMessageTime)
        } else {
            views.setTextViewText(R.id.widget_last_message, "点击打开聊天...")
            views.setTextViewText(R.id.widget_message_time, "")
        }

        // 设置点击事件：打开主应用
        val openAppIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("open_chat", true)
        }
        val openAppPendingIntent = PendingIntent.getActivity(
            context,
            0,
            openAppIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        views.setOnClickPendingIntent(R.id.widget_last_message, openAppPendingIntent)

        // 设置快速输入点击事件（打开聊天）
        val quickInputIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("open_chat", true)
            putExtra("focus_input", true)
        }
        val quickInputPendingIntent = PendingIntent.getActivity(
            context,
            1,
            quickInputIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        views.setOnClickPendingIntent(R.id.widget_quick_input, quickInputPendingIntent)

        // 设置 + 按钮点击事件（打开更多功能）
        val addMoreIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("open_drawer", true)
        }
        val addMorePendingIntent = PendingIntent.getActivity(
            context,
            3,
            addMoreIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        views.setOnClickPendingIntent(R.id.widget_add_button, addMorePendingIntent)

        // 设置刷新按钮点击事件
        val refreshIntent = Intent(context, AvelineWidgetProvider::class.java).apply {
            action = ACTION_REFRESH
        }
        val refreshPendingIntent = PendingIntent.getBroadcast(
            context,
            2,
            refreshIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        views.setOnClickPendingIntent(R.id.widget_send_button, refreshPendingIntent)

        appWidgetManager.updateAppWidget(appWidgetId, views)
    }

    private fun getEmotionIconRes(): Int {
        // 使用应用图标作为默认，实际可以创建不同情绪的图标
        return R.mipmap.ic_launcher
    }

    private fun sendQuickMessage(context: Context, message: String) {
        // 通过 Intent 将消息发送到主应用
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("send_message", message)
        }
        context.startActivity(intent)

        Toast.makeText(context, "消息已发送", Toast.LENGTH_SHORT).show()
    }
}
