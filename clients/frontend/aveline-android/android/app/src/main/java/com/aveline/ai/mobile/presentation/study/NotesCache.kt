package com.aveline.ai.mobile.presentation.study

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File

/**
 * 学习库笔记本地磁盘缓存（单向：后端 → 手机本地，只读镜像）。
 *
 * 解决：同一篇大笔记反复展开时不再每次走网络；已缓存的笔记离线也能看。
 *
 * 存储结构：
 * - <filesDir>/study-library/<rel_path>        镜像后端学习库的 .md 文件（rel_path 含科目子目录）
 * - <filesDir>/study-library/index.json        记录每个 rel_path -> 后端 updated_ts，用于增量判断
 *
 * 注意：后端返回的 updated_ts 来自电脑磁盘修改时间，本身是可靠的"内容是否变化"判据，
 * 因此以它为准做增量，不做内容 hash 比较（省 IO）。
 */
class NotesCache(context: Context) {
    private val rootDir = File(context.filesDir, "study-library").apply { mkdirs() }
    private val indexFile = File(rootDir, "index.json")

    private val json = Json { encodeDefaults = true }

    /** 读取 index：rel_path -> updated_ts */
    private fun readIndex(): MutableMap<String, Long> {
        if (!indexFile.isFile) return mutableMapOf()
        return runCatching {
            val obj = json.parseToJsonElement(indexFile.readText()).jsonObject
            obj.mapValues { (_, v) -> v.jsonPrimitive.int.toLong() }.toMutableMap()
        }.getOrDefault(mutableMapOf())
    }

    private fun writeIndex(index: Map<String, Long>) {
        runCatching {
            val arr = buildJsonArray {
                index.forEach { (path, ts) ->
                    add(buildJsonObject {
                        put("path", path)
                        put("ts", ts)
                    })
                }
            }
            indexFile.writeText(arr.toString())
        }
    }

    /** 本地是否存在该路径的缓存文件 */
    private fun localFile(relPath: String): File = File(rootDir, relPath)

    /**
     * 该笔记是否需要从后端刷新：
     * - 本地文件不存在 → 需要
     * - index 中记录的 ts 与最新 ts 不一致 → 需要
     */
    fun needsRefresh(relPath: String, latestTs: Long): Boolean {
        val local = localFile(relPath)
        if (!local.isFile) return true
        val index = readIndex()
        return index[relPath] != latestTs
    }

    /** 读取本地缓存内容；不存在或读取失败返回 null */
    fun readContent(relPath: String): String? {
        return runCatching { localFile(relPath).takeIf { it.isFile }?.readText() }.getOrNull()
    }

    /**
     * 写入缓存：内容存到镜像路径，ts 更新进 index。
     */
    fun write(relPath: String, content: String, ts: Long) {
        runCatching {
            val file = localFile(relPath)
            file.parentFile?.mkdirs()
            file.writeText(content)
            val index = readIndex()
            index[relPath] = ts
            writeIndex(index)
        }
    }

    /** 列出所有缓存文件（用于调试/清理，暂未使用） */
    @Suppress("unused")
    fun cachedPaths(): List<String> = readIndex().keys.toList()
}
