package com.aveline.core

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView

class MainActivity : AppCompatActivity() {
    private lateinit var chatAdapter: ChatAdapter
    private val messages = mutableListOf<ChatMessage>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // IP Configuration
        val etServerIp = findViewById<EditText>(R.id.etServerIp)
        val btnSaveIp = findViewById<Button>(R.id.btnSaveIp)
        val prefs = getSharedPreferences("config", MODE_PRIVATE)
        
        val savedIp = prefs.getString("server_ip", "10.0.2.2:5000")
        etServerIp.setText(savedIp)
        HttpClient.baseUrl = if (savedIp!!.startsWith("http")) savedIp else "http://$savedIp"

        btnSaveIp.setOnClickListener {
            val rawIp = etServerIp.text.toString().trim()
            if (rawIp.isNotEmpty()) {
                val newIp = if (rawIp.startsWith("http")) rawIp else "http://$rawIp"
                prefs.edit().putString("server_ip", rawIp).apply() // Save raw input for better UX
                HttpClient.baseUrl = newIp
                android.widget.Toast.makeText(this, "Server IP updated to $newIp", android.widget.Toast.LENGTH_SHORT).show()
            }
        }

        // Check Permissions Hint
        if (!Settings.canDrawOverlays(this)) {
             android.widget.Toast.makeText(this, "Please click '浮窗' to grant Overlay Permission", android.widget.Toast.LENGTH_LONG).show()
        }

        // Initialize Chat UI
        val recyclerView = findViewById<RecyclerView>(R.id.recyclerView)
        val etInput = findViewById<EditText>(R.id.etInput)
        val btnSend = findViewById<Button>(R.id.btnSend)
        
        chatAdapter = ChatAdapter(messages)
        recyclerView.adapter = chatAdapter
        recyclerView.layoutManager = LinearLayoutManager(this)

        // Add welcome message
        chatAdapter.addMessage(ChatMessage("Hello! I'm Aveline. You can chat with me here. Also, long-press the Volume Down key to analyze your screen anytime!", false))

        btnSend.setOnClickListener {
            val text = etInput.text.toString().trim()
            if (text.isNotEmpty()) {
                // Add user message
                chatAdapter.addMessage(ChatMessage(text, true))
                recyclerView.scrollToPosition(messages.size - 1)
                etInput.text.clear()

                // Send to backend
                HttpClient.postMessage(this, text) { res ->
                    runOnUiThread {
                        val content = res["content"] as? String ?: res["message"] as? String ?: "Error processing request"
                        val audio = res["audio"] as? String ?: res["audio_base64"] as? String
                        
                        chatAdapter.addMessage(ChatMessage(content, false, audio))
                        recyclerView.scrollToPosition(messages.size - 1)

                        if (!audio.isNullOrEmpty()) {
                            AudioPlayer.playBase64(this@MainActivity, audio)
                        }
                    }
                }
            }
        }

        // Overlay Permission Logic
        val btnOverlay = findViewById<Button>(R.id.btnOverlay)
        btnOverlay.setOnClickListener {
            if (!Settings.canDrawOverlays(this)) {
                val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                startActivity(intent)
            } else {
                AvelineOverlay.ensure(this)
                AvelineOverlay.setStatus("idle")
            }
        }
    }
}
