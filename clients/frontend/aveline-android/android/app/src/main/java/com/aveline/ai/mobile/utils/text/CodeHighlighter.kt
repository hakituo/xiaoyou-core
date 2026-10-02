package com.aveline.ai.mobile.utils.text

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import dev.snipme.highlights.Highlights
import dev.snipme.highlights.model.BoldHighlight
import dev.snipme.highlights.model.ColorHighlight
import dev.snipme.highlights.model.SyntaxLanguage
import dev.snipme.highlights.model.SyntaxThemes

/**
 * 代码块语法高亮与语言识别。
 *
 * 语言来源分两级：
 * 1. fence 标签：模型输出的 ```` ```python ```` 基本都自带语言标记，优先用它；
 * 2. 启发式识别：标签缺失或不认识时，按各语言特征 token 计分（[LANGUAGE_HINTS]）。
 *    Highlights 库本身没有提供语言自动识别 API，这一步是本地补齐的。
 *
 * 高亮映射与 KodeView（Highlights 官方 Compose 组件）的
 * `List<CodeHighlight>.generateAnnotatedString` 一致：
 * `ColorHighlight(location, rgb)` -> `SpanStyle(color = Color(rgb).copy(alpha = 1f))`，
 * `BoldHighlight(location)` -> `SpanStyle(fontWeight = Bold)`，
 * 区间为 `location.start` 到 `location.end`。
 */
object CodeHighlighter {

    /** fence 标记 -> 语言（覆盖常见别名；不认识的标签走库自带 getByName，再不行走启发式）。 */
    private val TAG_ALIASES: Map<String, SyntaxLanguage> = mapOf(
        "python" to SyntaxLanguage.PYTHON,
        "py" to SyntaxLanguage.PYTHON,
        "python3" to SyntaxLanguage.PYTHON,
        "javascript" to SyntaxLanguage.JAVASCRIPT,
        "js" to SyntaxLanguage.JAVASCRIPT,
        "jsx" to SyntaxLanguage.JAVASCRIPT,
        "node" to SyntaxLanguage.JAVASCRIPT,
        // JSON 是 JS 子集，按 JS 着色（字符串/数字/布尔）足够
        "json" to SyntaxLanguage.JAVASCRIPT,
        "typescript" to SyntaxLanguage.TYPESCRIPT,
        "ts" to SyntaxLanguage.TYPESCRIPT,
        "tsx" to SyntaxLanguage.TYPESCRIPT,
        "kotlin" to SyntaxLanguage.KOTLIN,
        "kt" to SyntaxLanguage.KOTLIN,
        "kts" to SyntaxLanguage.KOTLIN,
        "java" to SyntaxLanguage.JAVA,
        "c" to SyntaxLanguage.C,
        "h" to SyntaxLanguage.C,
        "cpp" to SyntaxLanguage.CPP,
        "c++" to SyntaxLanguage.CPP,
        "cxx" to SyntaxLanguage.CPP,
        "csharp" to SyntaxLanguage.CSHARP,
        "cs" to SyntaxLanguage.CSHARP,
        "c#" to SyntaxLanguage.CSHARP,
        "go" to SyntaxLanguage.GO,
        "golang" to SyntaxLanguage.GO,
        "rust" to SyntaxLanguage.RUST,
        "rs" to SyntaxLanguage.RUST,
        "ruby" to SyntaxLanguage.RUBY,
        "rb" to SyntaxLanguage.RUBY,
        "shell" to SyntaxLanguage.SHELL,
        "sh" to SyntaxLanguage.SHELL,
        "bash" to SyntaxLanguage.SHELL,
        "zsh" to SyntaxLanguage.SHELL,
        "php" to SyntaxLanguage.PHP,
        "swift" to SyntaxLanguage.SWIFT,
        "dart" to SyntaxLanguage.DART,
        "perl" to SyntaxLanguage.PERL,
        "coffeescript" to SyntaxLanguage.COFFEESCRIPT,
        "coffee" to SyntaxLanguage.COFFEESCRIPT,
    )

    /** 无标签时的启发式特征 token（小写匹配；分数最高的语言胜出）。 */
    private val LANGUAGE_HINTS: List<Pair<SyntaxLanguage, List<String>>> = listOf(
        SyntaxLanguage.PYTHON to listOf("def ", "elif", "__init__", "self.", "import ", "print("),
        SyntaxLanguage.KOTLIN to listOf("fun ", "val ", "when {", "println(", "else ->", "package "),
        SyntaxLanguage.JAVA to listOf("public class", "system.out", "@override", "void ", "private "),
        SyntaxLanguage.JAVASCRIPT to listOf("const ", "=>", "console.log", "function ", "document."),
        SyntaxLanguage.TYPESCRIPT to listOf(": string", ": number", "interface ", "export type", ": boolean"),
        SyntaxLanguage.GO to listOf("package main", "func ", ":= ", "fmt.", "go func"),
        SyntaxLanguage.RUST to listOf("fn ", "let mut", "match ", "impl ", "unwrap()"),
        SyntaxLanguage.SHELL to listOf("#!/bin/", "fi\n", "then\n", "sudo ", "apt-get"),
        SyntaxLanguage.RUBY to listOf("puts ", "require '", "attr_accessor"),
        SyntaxLanguage.PHP to listOf("<?php", "$this->", "echo "),
        SyntaxLanguage.SWIFT to listOf("guard ", "let ", "nslog", "import uikit"),
        SyntaxLanguage.CPP to listOf("#include", "std::", "cout <<"),
        SyntaxLanguage.C to listOf("#include <stdio", "printf(", "malloc("),
        SyntaxLanguage.DART to listOf("import 'package:", "widget build", "void main()"),
        SyntaxLanguage.CSHARP to listOf("using system", "console.writeline", "namespace "),
        SyntaxLanguage.PERL to listOf("use strict", "my $"),
        SyntaxLanguage.COFFEESCRIPT to listOf("@", "->"),
    )

    /**
     * 解析代码块语言：优先 fence 标签，缺失或不认识时用启发式识别。
     *
     * @param languageTag fence 行 ` ``` ` 之后的文本（可能为空）
     * @param code 代码块正文，标签缺失时用于启发式识别
     */
    fun resolveLanguage(languageTag: String?, code: String): SyntaxLanguage {
        val normalized = languageTag?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
        if (normalized != null) {
            TAG_ALIASES[normalized]?.let { return it }
            // 模型偶尔会写库认识但不在别名表里的写法
            SyntaxLanguage.getByName(normalized)?.let { return it }
        }
        return guessLanguage(code)
    }

    /** 无标签时的启发式识别：按特征 token 计分，取最高分；全零则返回 DEFAULT。 */
    fun guessLanguage(code: String): SyntaxLanguage {
        if (code.isBlank()) return SyntaxLanguage.DEFAULT
        val lower = code.lowercase()
        var best = SyntaxLanguage.DEFAULT
        var bestScore = 0
        for ((language, hints) in LANGUAGE_HINTS) {
            val score = hints.count { lower.contains(it) }
            // 平分时保持先出现的语言，避免识别结果抖动
            if (score > bestScore) {
                bestScore = score
                best = language
            }
        }
        return best
    }

    /** 语言的展示名（语言标签 chip 用）；DEFAULT 返回空串表示不显示标签。 */
    fun displayName(language: SyntaxLanguage): String = when (language) {
        SyntaxLanguage.DEFAULT -> ""
        SyntaxLanguage.CPP -> "C++"
        SyntaxLanguage.CSHARP -> "C#"
        SyntaxLanguage.JAVASCRIPT -> "JavaScript"
        SyntaxLanguage.TYPESCRIPT -> "TypeScript"
        SyntaxLanguage.COFFEESCRIPT -> "CoffeeScript"
        else -> language.name.lowercase().replaceFirstChar { it.uppercase() }
    }

    /**
     * 生成着色后的 [AnnotatedString]。
     *
     * 高亮失败（异常/空文本）时降级为原样返回，不抛错——
     * 渲染层拿到的一定是完整原文，最多没有颜色。
     */
    fun highlightCode(code: String, language: SyntaxLanguage): AnnotatedString {
        if (code.isBlank()) return AnnotatedString(code)
        val highlights = runCatching {
            Highlights.Builder()
                .code(code)
                .language(language)
                .theme(SyntaxThemes.default())
                .build()
                .getHighlights()
        }.getOrNull() ?: return AnnotatedString(code)

        return buildAnnotatedString {
            append(code)
            for (highlight in highlights) {
                val start = highlight.location.start
                val end = highlight.location.end
                // 越界区间直接跳过，避免 addStyle 抛 IndexOutOfBoundsException
                if (start < 0 || end <= start || end > code.length) continue
                when (highlight) {
                    is ColorHighlight -> addStyle(
                        // rgb 不含 alpha，必须补 1f，否则整体透明
                        SpanStyle(color = Color(highlight.rgb).copy(alpha = 1f)),
                        start,
                        end,
                    )
                    is BoldHighlight -> addStyle(
                        SpanStyle(fontWeight = FontWeight.Bold),
                        start,
                        end,
                    )
                }
            }
        }
    }
}
