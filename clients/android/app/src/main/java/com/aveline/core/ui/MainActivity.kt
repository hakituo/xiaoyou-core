package com.aveline.core.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.aveline.core.R
import com.aveline.core.infra.HttpClient
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    private val scope = MainScope()
    private lateinit var adapter: ChatAdapter
    private val messages = mutableListOf<ChatMessage>()

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Init UI
        val etServerIp = findViewById<EditText>(R.id.etServerIp)
        val btnSaveIp = findViewById<Button>(R.id.btnSaveIp)
        val btnOverlay = findViewById<Button>(R.id.btnOverlay)
        val rvChat = findViewById<RecyclerView>(R.id.recyclerView)
        val etInput = findViewById<EditText>(R.id.etInput)
        val btnSend = findViewById<Button>(R.id.btnSend)

        // Init Config
        val prefs = getSharedPreferences("config", MODE_PRIVATE)
        val savedIp = prefs.getString("server_ip", "http://10.0.2.2:5000")
        etServerIp.setText(savedIp)
        if (savedIp != null) {
            HttpClient.updateBaseUrl(savedIp)
        }

        // Init Adapter
        adapter = ChatAdapter(messages)
        rvChat.layoutManager = LinearLayoutManager(this)
        rvChat.adapter = adapter

        // Listeners
        btnSaveIp.setOnClickListener {
            val newIp = etServerIp.text.toString().trim()
            if (newIp.isNotEmpty()) {
                prefs.edit().putString("server_ip", newIp).apply()
                HttpClient.updateBaseUrl(newIp)
                Toast.makeText(this, "Server IP Saved", Toast.LENGTH_SHORT).show()
            }
        }

        btnOverlay.setOnClickListener {
            if (!Settings.canDrawOverlays(this)) {
                Toast.makeText(this, "Please grant Overlay Permission", Toast.LENGTH_LONG).show()
                val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                startActivity(intent)
            } else {
                AvelineOverlay.ensure(this)
                Toast.makeText(this, "Overlay Enabled", Toast.LENGTH_SHORT).show()
            }
        }

        btnSend.setOnClickListener {
            val text = etInput.text.toString().trim()
            if (text.isNotEmpty()) {
                sendMessage(text)
                etInput.setText("")
            }
        }
        
        // Auto-check overlay on start (optional, maybe annoying if it pops up every time)
        // if (Settings.canDrawOverlays(this)) {
        //    AvelineOverlay.ensure(this)
        // }
        
        startPolling()
    }

    private fun startPolling() {
        scope.launch {
            while (true) {
                try {
                    val notifications = HttpClient.getNotifications()
                    for (n in notifications) {
                        handleNotification(n)
                    }
                } catch (e: Exception) {
                    // Ignore errors during poll
                }
                kotlinx.coroutines.delay(5000)
            }
        }
    }

    private fun handleNotification(n: Map<String, Any?>) {
        val type = n["type"] as? String
        val title = n["title"] as? String ?: "Notification"
        val content = n["content"] as? String ?: ""
        val payload = n["payload"] as? Map<String, Any?>

        runOnUiThread {
            when (type) {
                "vocabulary" -> {
                    val fullText = payload?.get("full_text") as? String ?: content
                    val msg = ChatMessage("【$title】\n$fullText", false)
                    adapter.addMessage(msg)
                    scrollToBottom()
                }
                "voice" -> {
                    val text = payload?.get("text") as? String ?: content
                    // TODO: Fetch audio if needed
                    val msg = ChatMessage(text, false)
                    adapter.addMessage(msg)
                    scrollToBottom()
                }
                else -> {
                    val msg = ChatMessage("[$title] $content", false)
                    adapter.addMessage(msg)
                    scrollToBottom()
                }
            }
        }
    }

    private fun sendMessage(text: String) {
        // Add User Message
        val userMsg = ChatMessage(text, true)
        adapter.addMessage(userMsg)
        scrollToBottom()

        scope.launch {
            try {
                val res = HttpClient.postMessage(text)
                val reply = res["content"] as? String ?: res["reply"] as? String ?: ""
                val audio = res["audio_base64"] as? String

                if (reply.isNotEmpty()) {
                    val botMsg = ChatMessage(reply, false, audio)
                    adapter.addMessage(botMsg)
                    scrollToBottom()
                } else {
                     val errorMsg = ChatMessage("[Error] Empty response", false)
                     adapter.addMessage(errorMsg)
                }
            } catch (e: Exception) {
                val errorMsg = ChatMessage("[Error] ${e.message}", false)
                adapter.addMessage(errorMsg)
            }
        }
    }

    private fun scrollToBottom() {
        if (messages.isNotEmpty()) {
            findViewById<RecyclerView>(R.id.recyclerView).smoothScrollToPosition(messages.size - 1)
        }
    }
}
