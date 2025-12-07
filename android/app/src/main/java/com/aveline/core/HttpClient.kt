package com.aveline.core

import android.content.Context
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import org.json.JSONObject
import java.io.IOException
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

    fun postAnalyze(context: Context, imageBase64: String, cb: (Map<String, Any?>) -> Unit) {
        val json = JSONObject()
        json.put("image_base64", imageBase64)
        post("/api/v1/analyze_screen", json, cb)
    }

    fun postMessage(context: Context, text: String, cb: (Map<String, Any?>) -> Unit) {
        val json = JSONObject()
        json.put("content", text)
        post("/api/v1/message", json, cb)
    }

    private fun post(endpoint: String, json: JSONObject, cb: (Map<String, Any?>) -> Unit) {
        val body = RequestBody.create("application/json".toMediaType(), json.toString())
        val req = Request.Builder().url("$baseUrl$endpoint").post(body).build()
        
        Log.d(TAG, "POST $endpoint")
        
        client.newCall(req).enqueue(object: okhttp3.Callback {
            override fun onFailure(call: okhttp3.Call, e: IOException) {
                Log.e(TAG, "Request failed: ${e.message}")
                cb(mapOf("status" to "error", "content" to "Connection error: ${e.message}"))
            }

            override fun onResponse(call: okhttp3.Call, response: okhttp3.Response) {
                val responseBody = response.body?.string() ?: "{}"
                if (!response.isSuccessful) {
                    Log.e(TAG, "Server error: ${response.code} $responseBody")
                    cb(mapOf("status" to "error", "content" to "Server error: ${response.code}"))
                    return
                }

                try {
                    val o = JSONObject(responseBody)
                    val map = mutableMapOf<String, Any?>()
                    val keys = o.keys()
                    while (keys.hasNext()) {
                        val k = keys.next()
                        map[k] = o.opt(k)
                    }
                    cb(map)
                } catch (e: Exception) {
                    Log.e(TAG, "JSON parse error: ${e.message}")
                    cb(mapOf("status" to "error", "content" to "Parse error"))
                }
            }
        })
    }
}
