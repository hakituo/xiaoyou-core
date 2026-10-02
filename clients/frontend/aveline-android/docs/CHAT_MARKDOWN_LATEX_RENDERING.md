# Android 聊天 Markdown / LaTeX 渲染链

> 更新时间：2026-09-13
>
> 适用范围：`clients/frontend/aveline-android/android/` 的聊天 AI 消息、学习笔记和日记正文。

## 目标

聊天正文必须满足两点：一是 Markdown 与 LaTeX 不能因为“消息断句”而丢失块结构；二是普通文本、粗体、删除线与行内公式必须在同一个 Compose paragraph 中参与换行，不能再用 `Row` 把它们拆成互相争抢剩余宽度的 child。

当前链路：

```text
MessageBubble
  -> TextSegmenter.splitForDisplay()
  -> NotesMarkdownRenderer
  -> MarkdownBlockParser.parse(text)       // remember(text)
  -> MarkdownInlineParser                  // 标题/段落/列表/引用/表格 cell 共用
  -> MarkdownInlineText                    // AnnotatedString + InlineTextContent
  -> LatexMath / MTMathView
```

`SimpleDiaryMarkdown` 也直接复用 `NotesMarkdownRenderer`，不再维护第二套 `Row(Text + LatexMath + Text)` 行内渲染器。

## 展示前断句保护

`TextSegmenter.splitForDisplay()` 对块级 Markdown 和块级 LaTeX 采用“整段透传”策略。只要文本中出现未转义的 `$$` marker，就不再进入聊天碎句器。

这里故意不要求 `$$` 已经成对闭合，因为 SSE / WebSocket 流式输出过程中经常先收到：

```text
下面开始推导
$$
F=-k
```

如果等第二个 `$$` 到达后才保护，前面的流式帧已经可能按换行拆成多个 display segment，renderer 无法恢复原块。

## Block AST

`MarkdownBlockParser` 是纯 Kotlin 状态机，优先级固定为：

```text
fenced code > math block > table / heading / list / quote / paragraph
```

因此代码块中的 `$$` 永远是代码文本，不会切换数学状态。支持：

- 多行块公式：独立的 `$$` 开始 / 结束；
- 单行块公式：`$$E=mc^2$$`；
- `#` 到 `######` 标题；
- `-` / `*` / `+` 列表；
- 多层 `>` 引用；
- fenced code（``` 与 ~~~）；
- GFM 风格表格；
- `---` / `***` / `___` 分隔线。

GFM 表格的 `|:---|---:|`、`|---|---|` 等 separator 在 parser 阶段删除，不再被当作数据行。

`NotesMarkdownRenderer` 使用：

```kotlin
val blocks = remember(text) { MarkdownBlockParser.parse(text) }
```

因此主题、滚动、父组件状态等普通 Compose recomposition 不会重新扫描整篇 Markdown；只有实际消息文本变化时重新解析。流式 token 到达会产生新的 `text`，此时重新解析属于预期行为。

## 列表圆点布局

无序列表继续使用 `Primary` 蓝色圆点，但 marker 不再占一条固定 `20.dp` 的左侧列。圆点按自身字宽参与 `Row` 布局，与正文之间只保留约 `6.dp` 的间距，并通过 `alignByBaseline()` 与正文第一行共用 baseline。

这样短列表项看起来就是“圆点直接对应在文字旁边”，长列表项换成多行时圆点仍然只对应第一行，不会因为整段高度变大而跑到中间位置。

## 行内 Markdown / LaTeX

`MarkdownInlineParser` 解析：

- `**bold**`
- `*italic*`
- `~~strike~~`
- `$inline math$`
- `$$display math$$`
- `\$`、`\*`、`\~`、`\\` 转义

标题、普通段落、列表、引用和表格 cell 都使用同一个行内 parser，因此不会再出现“正文支持公式，但标题/表格把源码直接显示出来”的分叉行为。

`$$...$$` 有两种落点：整行以 `$$` 开头/结尾时由 `MarkdownBlockParser` 生成 `MarkdownBlock.Math`（居中块级排版）；
出现在列表项/标题/表格 cell 内部时由行内 parser 兜住，生成行内 `Math` 节点。这样 `- 胡克定律：$$F=-kx$$`
不会把两个美元符号原样显示出来。流式输出只到一半（没有收尾 `$$`）时退化成原样文本，不会闪成半截乱码。

单星号按 CommonMark 的 flank 规则判定：开标记右侧不能是空白、闭标记左侧不能是空白，且闭合星号左右都不能
紧贴另一个星号。因此 `2 * 3 * 4`、`标注*` 保持原样，而 `*说明 **重点** 结束` 里的加粗定界符也不会被斜体抢走。

美元符号不再通过“文本里只要有 `$` 就切换旧 renderer”处理。解析器只有确认存在可闭合且看起来像数学表达式的 `$...$` 时才生成 Math node；明显的自然语言货币写法，例如：

```text
这个套餐 $20，另一个是 $30
```

会保持普通文本。需要明确输出美元符号时可以写 `\$`。

## 单一 Text 行内布局

`MarkdownInlineText` 将普通/粗体/斜体/删除线全部写入同一个 `AnnotatedString`，行内公式用 Compose `InlineTextContent` 在同一个 Text paragraph 中预留占位并嵌入 `LatexMath`。

旧实现：

```text
Row
  Text("速度满足 ")
  LatexMath("v=v0+at")
  Text("，所以如果初速度……")
```

后面的 Text 只能拿到当前 Row 剩余宽度，换行后仍可能保持窄约束，形成右侧竖排或异常截断。

新实现：

```text
Text(
  AnnotatedString("速度满足 [inline-math]，所以如果初速度……"),
  inlineContent = ...
)
```

公式前后的长文本由一个 paragraph 统一测量和换行。特别长或高的公式仍应使用 `$$...$$` 块级形式；块公式保持独立横向滚动。

## 测试与验证

纯 Kotlin parser 回归测试：

- `MarkdownInlineParserTest.kt`
- `MarkdownBlockParserTest.kt`
- `MarkdownLatexSegmenterTest.kt`

覆盖 `$x$`、`\$20`、`$20 ... $30`、`$$x$$`、多行数学块、代码块内 `$$`、标题/表格公式、GFM 对齐 separator，以及流式阶段只有起始 `$$` 时的展示整段保护。

静态接线检查仍由 `tests/scripts/android_frontend/verify_chat_markdown_rendering.py` 负责，但它只验证关键代码路径没有被误删，不能替代 Android 编译和真机视觉验收。

按照仓库 `AGENTS.md` 的 Android 规则，本次不在沙箱运行 Gradle。最终需要在 Android Studio 编译，并在聊天页至少人工检查下面这组输入：

````markdown
速度满足 $v=v_0+at$，所以如果初速度很小，后面的长文字也应该自然占满整行并换行。

- 第一条短列表
- 第二条是一段比较长的列表内容，用来确认蓝色圆点紧贴正文第一行，并且换行后不会跑到整段中间

$$
F=-kx
$$

$$E=mc^2$$

这个套餐 $20，另一个是 $30，转义价格为 \$40。

```text
$$
hello
$$
```

## **动能** $E_k=\frac12mv^2$

| 量 | 公式 |
|:---|---:|
| 力 | $F=ma$ |
````
