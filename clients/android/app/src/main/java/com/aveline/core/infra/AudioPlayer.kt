package com.aveline.core.infra

import android.content.Context
import android.media.MediaPlayer
import android.net.Uri
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

object AudioPlayer {
    private var player: MediaPlayer? = null

    suspend fun playBase64(context: Context, dataUrl: String) = withContext(Dispatchers.IO) {
        try {
            val parts = dataUrl.split(",")
            val bytes = Base64.decode(if (parts.size > 1) parts[1] else parts[0], Base64.DEFAULT)
            val f = File(context.cacheDir, "aveline_tts.wav")
            f.writeBytes(bytes)

            withContext(Dispatchers.Main) {
                player?.release()
                player = MediaPlayer().apply {
                    setDataSource(context, Uri.fromFile(f))
                    prepare() 
                    setOnCompletionListener {
                        try { it.release() } catch (_: Exception) {}
                        player = null
                    }
                    setOnErrorListener { mp, _, _ ->
                        try { mp.release() } catch (_: Exception) {}
                        player = null
                        false
                    }
                    start()
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}
