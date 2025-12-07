package com.aveline.core

import android.content.Context
import android.media.MediaPlayer
import android.net.Uri
import android.util.Base64
import java.io.File

object AudioPlayer {
    private var player: MediaPlayer? = null
    fun playBase64(context: Context, dataUrl: String) {
        try {
            val parts = dataUrl.split(",")
            val bytes = Base64.decode(if (parts.size>1) parts[1] else parts[0], Base64.DEFAULT)
            val f = File(context.cacheDir, "aveline_tts.wav")
            f.writeBytes(bytes)
            player?.release()
            player = MediaPlayer()
            player!!.setDataSource(context, Uri.fromFile(f))
            player!!.prepare()
            player!!.setOnCompletionListener {
                try { it.release() } catch (_: Exception) {}
                player = null
            }
            player!!.setOnErrorListener { mp, _, _ ->
                try { mp.release() } catch (_: Exception) {}
                player = null
                false
            }
            player!!.start()
        } catch (_: Exception) {}
    }
}
