package com.aveline.ai.mobile.presentation.study

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * StudyJsonExtensions 回归测试
 *
 * 重点验证 P0-4 修复:字段为 JsonObject/JsonArray(非基本类型)时,
 * 读取函数不应抛 IllegalStateException,而应返回 null/空串。
 * 修复前 `this[key]?.jsonPrimitive` 对非 JsonPrimitive 会抛异常导致崩溃。
 */
class StudyJsonExtensionsTest {

    @Test
    fun `string 读取基本字符串字段`() {
        val obj = buildJsonObject { put("name", "Aveline") }
        assertEquals("Aveline", obj.string("name"))
    }

    @Test
    fun `string 缺失字段返回空串`() {
        val obj = buildJsonObject { put("other", "x") }
        assertEquals("", obj.string("name"))
    }

    @Test
    fun `string 字段为 JsonObject 时不崩溃且返回空串`() {
        // P0-4 核心场景:后端返回嵌套对象,修复前会崩溃
        val obj = buildJsonObject {
            put("nested", buildJsonObject { put("inner", "value") })
        }
        assertEquals("", obj.string("nested"))
    }

    @Test
    fun `string 字段为 JsonArray 时不崩溃且返回空串`() {
        val obj = buildJsonObject {
            put("list", buildJsonArray { add("a"); add("b") })
        }
        assertEquals("", obj.string("list"))
    }

    @Test
    fun `int 读取整数正常`() {
        val obj = buildJsonObject { put("count", JsonPrimitive(42)) }
        assertEquals(42, obj.int("count"))
    }

    @Test
    fun `int 字段为 JsonObject 时返回 null 不崩溃`() {
        val obj = buildJsonObject {
            put("nested", buildJsonObject { put("x", 1) })
        }
        assertNull(obj.int("nested"))
    }

    @Test
    fun `int 字段为字符串时返回 null`() {
        val obj = buildJsonObject { put("count", "not-a-number") }
        assertNull(obj.int("count"))
    }

    @Test
    fun `long 字段为 JsonObject 时返回 null 不崩溃`() {
        val obj = buildJsonObject {
            put("nested", buildJsonObject { put("x", 1) })
        }
        assertNull(obj.long("nested"))
    }

    @Test
    fun `boolean 字段为 JsonObject 时返回 null 不崩溃`() {
        val obj = buildJsonObject {
            put("nested", buildJsonObject { put("x", true) })
        }
        assertNull(obj.boolean("nested"))
    }

    @Test
    fun `double 字段为 JsonArray 时返回 null 不崩溃`() {
        val obj = buildJsonObject {
            put("list", buildJsonArray { add(1.0) })
        }
        assertNull(obj.double("list"))
    }

    @Test
    fun `orEmptyArray null 返回空数组`() {
        val arr: JsonArray? = null
        assertEquals(0, arr.orEmptyArray().size)
    }

    @Test
    fun `orEmptyArray 非空返回原数组`() {
        val arr = buildJsonArray { add("a"); add("b") }
        assertEquals(arr, arr.orEmptyArray())
    }

    @Test
    fun `解析真实 study_panel 响应不崩溃`() {
        // 模拟后端真实响应结构
        val responseJson = """
        {
            "data": {
                "study_panel": {
                    "title": "本周学习概览",
                    "summary": "持续学习中",
                    "study_streak_days": 5,
                    "reviewed_today": 12
                },
                "workspace_snapshot": {
                    "portrait": {
                        "study": {
                            "total_minutes": 120,
                            "sessions": [
                                {"topic": "数学", "content": "微积分", "time": "2026-07-28"}
                            ]
                        }
                    }
                }
            }
        }
        """.trimIndent()
        val response = Json.parseToJsonElement(responseJson).jsonObject
        val data = response["data"]!!.jsonObject
        val panel = data["study_panel"]!!.jsonObject

        assertEquals("本周学习概览", panel.string("title"))
        assertEquals(5, panel.int("study_streak_days"))
        assertEquals(12, panel.int("reviewed_today"))

        // 嵌套对象读取不应崩溃
        assertEquals("", panel.string("data"))
        assertNull(panel.int("study_panel"))
    }
}
