package com.aveline.core.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.aveline.core.R
import com.aveline.core.infra.AudioPlayer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

data class ChatMessage(val text: String, val isUser: Boolean, val audioData: String? = null)

class ChatAdapter(private val messages: MutableList<ChatMessage>) :
    RecyclerView.Adapter<ChatAdapter.ChatViewHolder>() {

    class ChatViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val layoutBotMessage: LinearLayout = view.findViewById(R.id.layoutBotMessage)
        val tvBotMessage: TextView = view.findViewById(R.id.tvBotMessage)
        val btnPlayAudio: ImageButton = view.findViewById(R.id.btnPlayAudio)
        val tvUserMessage: TextView = view.findViewById(R.id.tvUserMessage)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ChatViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_chat_message, parent, false)
        return ChatViewHolder(view)
    }

    override fun onBindViewHolder(holder: ChatViewHolder, position: Int) {
        val message = messages[position]
        if (message.isUser) {
            holder.tvUserMessage.text = message.text
            holder.tvUserMessage.visibility = View.VISIBLE
            holder.layoutBotMessage.visibility = View.GONE
        } else {
            holder.tvBotMessage.text = message.text
            holder.layoutBotMessage.visibility = View.VISIBLE
            holder.tvUserMessage.visibility = View.GONE

            if (!message.audioData.isNullOrEmpty()) {
                holder.btnPlayAudio.visibility = View.VISIBLE
                holder.btnPlayAudio.setOnClickListener {
                    CoroutineScope(Dispatchers.Main).launch {
                        AudioPlayer.playBase64(holder.itemView.context, message.audioData)
                    }
                }
            } else {
                holder.btnPlayAudio.visibility = View.GONE
                holder.btnPlayAudio.setOnClickListener(null)
            }
        }
    }

    override fun getItemCount() = messages.size

    fun addMessage(message: ChatMessage) {
        messages.add(message)
        notifyItemInserted(messages.size - 1)
    }
}
