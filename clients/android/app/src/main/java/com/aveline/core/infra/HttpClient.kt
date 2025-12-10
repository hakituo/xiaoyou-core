package com.aveline.core.infra

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object HttpClient {
    private const val TAG = "HttpClient"
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .callTimeout(20, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()
    var baseUrl = "http://10.0.2.2:5000"

    fun updateBaseUrl(url: String) {
        baseUrl = url
        if (baseUrl.endsWith("/")) {
            baseUrl = baseUrl.dropLast(1)
        }
    }

    suspend fun postAnalyze(imageBase64: String): Map<String, Any?> {
        val json = JSONObject()
        json.put("image_base64", imageBase64)
        return post("/api/v1/analyze_screen", json)
    }

    suspend fun postMessage(text: String): Map<String, Any?> {
        val json = JSONObject()
        json.put("content", text)
        return post("/api/v1/message", json)
    }

    private suspend fun post(endpoint: String, json: JSONObject): Map<String, Any?> = withContext(Dispatchers.IO) {
        val body = json.toString().toRequestBody("application/json".toMediaType())
        val req = Request.Builder().url("$baseUrl$endpoint").post(body).build()
        
        Log.d(TAG, "POST $endpoint")
        
        try {
            client.newCall(req).execute().use { response ->
                val responseBody = response.body?.string() ?: "{}"
                if (!response.isSuccessful) {
                    Log.e(TAG, "Server error: ${response.code} $responseBody")
                    return@withContext mapOf("status" to "error", "content" to "Server error: ${response.code}")
                }

                try {
                    val o = JSONObject(responseBody)
                    val map = mutableMapOf<String, Any?>()
                    val keys = o.keys()
                    while (keys.hasNext()) {
                        val k = keys.next()
                        map[k] = o.opt(k)
                    }
                    return@withContext map
                } catch (e: Exception) {
                    Log.e(TAG, "JSON parse error: ${e.message}")
                    return@withContext mapOf("status" to "error", "content" to "Parse error")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Request failed: ${e.message}")
            return@withContext mapOf("status" to "error", "content" to "Connection error: ${e.message}")
        }
    }
}
