package com.aveline.ai.mobile.data.remote.api

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * SseParser 的回归测试。
 *
 * 覆盖历史 bug：后端 `routers/v1/chat.py` 有一部分错误分支（content 为空 /
 * 内容过长 / 消息格式非法）走的是 `return resp` 返回**普通 JSON**，HTTP 状态码
 * 仍是 200，并不是 SSE 流。旧实现强制要求行以 `data: ` 开头，于是整段 JSON
 * 被静默丢掉：一个 StreamEvent 都不发，UI 停在「正在输入」且**不弹任何错误**，
 * 安卓端表现为「AI 完全不回复」。
 *
 * 发图不带文案时 caption 为空串，正好命中 EMPTY_CONTENT 分支，
 * 就是这条静默路径导致的（与 d09261d 修的那条链路叠加）。
 */
class SseParserTest {

    @Test
    fun `正常 SSE chunk 解析为 Chunk`() {
        val line = """data: {"type":"message","subtype":"response_chunk","content":"你好"}"""
        assertEquals(StreamEvent.Chunk("你好"), SseParser.parse(line))
    }

    @Test
    fun `DONE 标记解析为 Done`() {
        assertEquals(StreamEvent.Done(), SseParser.parse("data: [DONE]"))
    }

    @Test
    fun `SSE 内的 error 事件解析为 Error`() {
        val line = """data: {"type":"error","message":"生成失败"}"""
        assertEquals(StreamEvent.Error("生成失败"), SseParser.parse(line))
    }

    /** 后端 EMPTY_CONTENT 分支真实返回的响应体（HTTP 200，非 SSE）。 */
    @Test
    fun `裸 JSON 错误响应兜底为 Error 且带上 error_code`() {
        val bare =
            """{"status":"error","message":"消息内容不能为空且必须是字符串",""" +
                """"detail":"消息内容不能为空且必须是字符串",""" +
                """"error":"消息内容不能为空且必须是字符串",""" +
                """"error_code":"EMPTY_CONTENT","details":{},"request_id":"abc","timestamp":1.0}"""
        val event = SseParser.parse(bare)
        assertTrue("裸 JSON 错误必须被识别，实际=$event", event is StreamEvent.Error)
        val message = (event as StreamEvent.Error).message
        assertTrue("错误要带 error_code 便于定位，实际=$message", message.contains("EMPTY_CONTENT"))
        assertTrue("错误要带可读文案，实际=$message", message.contains("消息内容不能为空"))
    }

    @Test
    fun `裸 JSON 错误没有 error_code 时只回退文案`() {
        val bare = """{"status":"error","message":"服务暂时不可用"}"""
        assertEquals(StreamEvent.Error("服务暂时不可用"), SseParser.parse(bare))
    }

    /** FastAPI 校验错误的 detail 是数组，不能因为取 jsonPrimitive 而抛异常。 */
    @Test
    fun `detail 为数组的校验错误不会崩溃`() {
        val bare = """{"detail":[{"loc":["body"],"msg":"field required","type":"value_error"}]}"""
        assertNull("detail 是数组时取不到文案，应安静忽略而不是抛异常", SseParser.parse(bare))
    }

    /** 成功响应不应该被当成错误，否则会把一次正常回复变成报错。 */
    @Test
    fun `成功的裸 JSON 不会被误判为 Error`() {
        val bare = """{"status":"success","response":"在。","request_id":"abc"}"""
        assertNull(SseParser.parse(bare))
    }

    @Test
    fun `空行与注释行忽略`() {
        assertNull(SseParser.parse(""))
        assertNull(SseParser.parse("   "))
        assertNull(SseParser.parse(": keep-alive"))
    }

    @Test
    fun `非 JSON 的 data 行忽略`() {
        assertNull(SseParser.parse("data: not-json"))
        assertNull(SseParser.parse("data: "))
    }
}
