# Life/Food/Shop/Status 模块代码审查报告

## 审查概览

本次审查覆盖 10 个文件,横跨 4 个功能模块(Life/Food/Shop/Status)以及被 Life 模块复用的 health 模块的 `DailyDataViewModel`。

| 文件 | 行数 | 严重 | 中等 | 轻微 |
|------|------|------|------|------|
| life/LifeHealthTab.kt | 98 | 0 | 0 | 1 |
| life/LifeMealTab.kt | 161 | 0 | 1 | 3 |
| life/LifeScheduleTab.kt | 135 | 0 | 1 | 2 |
| life/LifeScreen.kt | 257 | 0 | 3 | 1 |
| life/LifeWaterTab.kt | 120 | 0 | 1 | 2 |
| food/FoodItemCard.kt | 213 | 0 | 1 | 2 |
| food/FoodScreen.kt | 403 | 1 | 2 | 2 |
| shop/ShopViewModel.kt | 239 | 1 | 5 | 1 |
| status/StatusViewModel.kt | 270 | 2 | 5 | 1 |
| health/DailyDataViewModel.kt | 250 | 2 | 2 | 1 |
| **合计** | — | **6** | **21** | **16** |

主要问题类型:
- **架构问题**:UI 临时状态混入 ViewModel(`ShopUiState`)、JSON 解析逻辑下沉到 ViewModel(`DailyDataViewModel`)、依赖倒置违反(`StatusViewModel` 同时注入接口与实现)
- **并发与流问题**:多个 collector 未保存 Job、fire-and-forget 调用、无防重入保护
- **数据正确性 bug**:`ReconnectSync` 中 `health = status["energy"]`、`recordDrink` 参数语义与 UI 调用不匹配
- **Compose 性能**:`LazyColumn` 内用 `forEach` 渲染列表、`Map<String, Float>` 不稳定导致重组

---

## 逐文件审查

### life/LifeHealthTab.kt

#### 问题 1: 🟡 未使用的导入 `Color`
- 位置: LifeHealthTab.kt:17
- 问题描述: `import androidx.compose.ui.graphics.Color` 导入后未在文件中使用,属于代码冗余。Lint 检查会告警。
- 建议方案: 删除该导入。

#### 审查结论
该文件结构清晰,职责单一(纯展示型 Composable),无其他问题。`N/A` 占位项有注释说明"待后续接入",属于合理占位。

---

### life/LifeMealTab.kt

#### 问题 1: 🟠 `MealItem` 列表使用 `forEach` 而非 LazyColumn,且缺少 `key`
- 位置: LifeMealTab.kt:72-76
- 问题描述:
  ```kotlin
  Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
      uiState.meals.forEach { meal ->
          MealItem(meal = meal)
      }
  }
  ```
  `uiState.meals` 在 `SectionCard` 内部的 `Column` 中用 `forEach` 渲染。当 `meals` 列表较长时,所有 item 会一次性组合,失去懒加载优势;且 `forEach` 未传 `key`,列表发生变化(增删)时可能触发不必要的重组,甚至导致状态错位。
- 建议方案:
  - 若 `meals` 数量有上限且很小(<10),保留 `forEach` 但补上 `key`: `uiState.meals.forEach { meal -> key(meal.time + meal.type) { MealItem(meal) } }`(理想情况下应用业务主键)。
  - 若数量可能增长,改用 `LazyColumn` 或将整个 `SectionCard` 内容下沉到 `LazyColumn` 的 `item` 块中,并用 `items(meals, key = { ... })` 渲染。

#### 问题 2: 🟡 未使用的导入
- 位置: LifeMealTab.kt:22, 26
- 问题描述:
  - `import androidx.compose.runtime.remember`(line 22)未使用,代码用的是 `rememberSaveable`。
  - `import androidx.compose.ui.graphics.Color`(line 26)未使用。
- 建议方案: 删除这两个导入。

#### 问题 3: 🟡 `OutlinedTextField` 缺少 IME 与键盘配置
- 位置: LifeMealTab.kt:104-110
- 问题描述: 餐食内容输入框未配置 `KeyboardOptions`(如 `KeyboardCapitalization.Sentences`)和 `ImeAction`(如 `Done`/`Send`),用户体验较差;输入完后无法通过 IME 直接提交。
- 建议方案: 添加 `keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences)` 与 `keyboardActions = KeyboardActions(onDone = { /* 触发记录 */ })`。

#### 问题 4: 🟡 `mealContent` 清空但 `selectedMealType` 保留,行为合理但缺提示
- 位置: LifeMealTab.kt:115-127
- 问题描述: 点击"记录餐食"后,`mealContent` 被清空,但 `selectedMealType` 保留。这是合理设计(用户连续记录同类餐食),但缺少成功反馈(如 Snackbar 或临时 Toast),用户无法直观感知记录是否成功。
- 建议方案: 由父级通过 `uiState.message` 显示成功提示(已有该字段),或在按钮点击后短暂禁用并显示"已记录"。本文件不改,提示父级 UI 接入。

---

### life/LifeScheduleTab.kt

#### 问题 1: 🟠 `formatUnixTime` 使用 `SimpleDateFormat`,与项目其他模块不一致且非线程安全
- 位置: LifeScheduleTab.kt:130-135
- 问题描述:
  ```kotlin
  private fun formatUnixTime(timestampSeconds: Long): String {
      return runCatching {
          SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(timestampSeconds * 1000))
      }.getOrDefault("N/A")
  }
  ```
  - `SimpleDateFormat` 非线程安全(虽然这里局部使用风险低)。
  - 项目其他模块(`StatusViewModel`)已用 `java.time.format.DateTimeFormatter`,风格不统一。
  - 每次调用都新建 `SimpleDateFormat` 实例,有轻微开销。
- 建议方案: 改用 `java.time` API:
  ```kotlin
  private fun formatUnixTime(timestampSeconds: Long): String = runCatching {
      Instant.ofEpochSecond(timestampSeconds)
          .atZone(ZoneId.systemDefault())
          .format(DateTimeFormatter.ofPattern("MM-dd HH:mm"))
  }.getOrDefault("N/A")
  ```

#### 问题 2: 🟡 未使用的导入 `Color`
- 位置: LifeScheduleTab.kt:19
- 问题描述: `import androidx.compose.ui.graphics.Color` 未使用。
- 建议方案: 删除。

#### 问题 3: 🟡 `SessionItem` 列表同样使用 `forEach` 缺 `key`
- 位置: LifeScheduleTab.kt:79-83
- 问题描述: 与 `LifeMealTab` 相同,`uiState.studySessions.forEach` 缺少 `key`,列表变化时可能状态错位。
- 建议方案: 同上,用 `key(session.topic + session.time) { SessionItem(session) }` 或改用 `LazyColumn`。

---

### life/LifeScreen.kt

#### 问题 1: 🟠 4 个 Tab 内容结构高度重复
- 位置: LifeScreen.kt:196-253
- 问题描述: `LifeTab.HEALTH`、`LifeTab.WATER`、`LifeTab.SCHEDULE`、`LifeTab.MEAL` 4 个分支的 `Column + verticalScroll + Spacer + LifeXxxTab + Spacer` 结构完全一致,仅 Tab 内容不同。重复代码导致维护成本上升(如统一调整 padding 需改 4 处)。
- 建议方案: 抽取公共 Composable:
  ```kotlin
  @Composable
  private fun LifeTabPage(content: @Composable () -> Unit) {
      Column(
          modifier = Modifier.fillMaxSize()
              .verticalScroll(rememberScrollState())
              .padding(horizontal = 16.dp),
          verticalArrangement = Arrangement.spacedBy(16.dp)
      ) {
          Spacer(modifier = Modifier.height(8.dp))
          content()
          Spacer(modifier = Modifier.height(24.dp))
      }
  }
  ```
  然后 `when (tab) { LifeTab.HEALTH -> LifeTabPage { LifeHealthTab(...) } ... }`。

#### 问题 2: 🟠 `LaunchedEffect(pagerState.currentPage)` 在初始组合时即触发 `onTabChange`
- 位置: LifeScreen.kt:92-94
- 问题描述:
  ```kotlin
  LaunchedEffect(pagerState.currentPage) {
      onTabChange(tabs[pagerState.currentPage])
  }
  ```
  首次组合时 `pagerState.currentPage = 0`,会立即调用 `onTabChange(LifeTab.HEALTH)`。若父级已默认 `HEALTH`,这是多余回调;若父级基于该回调触发数据加载或副作用,可能引发非预期的级联更新。
- 建议方案: 若父级已知初始 tab,可加判断跳过首次:
  ```kotlin
  var firstEmission = true
  LaunchedEffect(pagerState.currentPage) {
      if (firstEmission) { firstEmission = false; return@LaunchedEffect }
      onTabChange(tabs[pagerState.currentPage])
  }
  ```
  或与父级确认该回调是否必要(若父级不依赖该回调,可直接删除)。

#### 问题 3: 🟠 HorizontalPager 远端 Tab 的滚动状态丢失
- 位置: LifeScreen.kt:183-255
- 问题描述: `HorizontalPager` 默认只保留相邻页的 Composable 状态,远离页被销毁。每个 Tab 内部用 `rememberScrollState()`,切换到远端 Tab 再回来时滚动位置会重置为顶部,用户体验差。
- 建议方案: 用 `rememberSaveable` 持久化滚动状态,或使用 `SaveableStateHolder`:
  ```kotlin
  val saveableStateHolder = rememberSaveableStateHolder()
  HorizontalPager(state = pagerState, ...) { page ->
      saveableStateHolder.SaveableStateProvider(key = page) {
          // 原有内容
      }
  }
  ```

#### 问题 4: 🟡 `Box` 包装冗余
- 位置: LifeScreen.kt:191-194
- 问题描述: 每个 page 内层用 `Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.TopStart)` 包裹 `Column`,但 `Column` 默认就是 `TopStart` 对齐,`Box` 没有提供额外价值,徒增一层嵌套。
- 建议方案: 直接用 `Column`,删除 `Box`。

---

### life/LifeWaterTab.kt

#### 问题 1: 🟠 `WATER_GOAL_ML` 硬编码,无法适配用户个性化目标
- 位置: LifeWaterTab.kt:29, 45, 54
- 问题描述: `private const val WATER_GOAL_ML = 2000` 写死 2000ml。不同体重/性别/运动量的用户每日饮水目标不同,硬编码会导致进度条计算不准确。
- 建议方案: 从 `DailyDataUiState` 或用户配置中读取目标值:
  ```kotlin
  val waterGoalMl = uiState.drinkGoalMl ?: 2000  // 默认 2000
  val progress = (totalMl.toFloat() / waterGoalMl).coerceIn(0f, 1f)
  ```
  并在 `DailyDataUiState` 添加 `drinkGoalMl: Int?` 字段。

#### 问题 2: 🟡 未使用的导入 `Color`
- 位置: LifeWaterTab.kt:18
- 问题描述: `import androidx.compose.ui.graphics.Color` 未使用。
- 建议方案: 删除。

#### 问题 3: 🟡 平均值计算依赖 `drinkCount != 0` 隐式保护
- 位置: LifeWaterTab.kt:98
- 问题描述: `${totalMl / uiState.drinkCount}` 当 `drinkCount == 0` 会除零,虽然 line 88 的 `if (uiState.drinkCount == 0)` 分支已阻止执行到此,但代码可读性差,未来重构若误删外层判断会引发崩溃。
- 建议方案: 显式安全除法:`${if (uiState.drinkCount > 0) totalMl / uiState.drinkCount else 0} ml/次`,或提取 `avgMl` 局部变量。

---

### food/FoodItemCard.kt

#### 问题 1: 🟠 硬编码颜色值散布于组件中,未走主题系统
- 位置: FoodItemCard.kt:65, 145, 155, 202-212
- 问题描述:
  - `Color(0x1A000000)`、`Color(0x12000000)`、`Color(0x2A38BDF8)`、`Color(0xFFFFE0B2)` 等颜色硬编码在组件中。
  - 这导致深色/浅色主题切换时无法自动适配,且颜色含义不直观(0x1A000000 是什么色?)。
- 建议方案: 将颜色提取到 `theme/` 包,定义为命名颜色(如 `CardOverlayEnabled`、`CardOverlayDisabled`),通过 `MaterialTheme.colorScheme` 或自定义 `LocalFoodCardColors` 提供。

#### 问题 2: 🟡 `TypeBadge` 文字与背景色通过 `when` 枚举映射,扩展性差
- 位置: FoodItemCard.kt:202-213
- 问题描述: `FoodCategory.iconColor()` 和 `badgeTextColor()` 用 `when (this)` 列举所有枚举值。若新增 `FoodCategory` 枚举值(如 `FRUIT`),两个函数都需要同步修改,容易遗漏。
- 建议方案: 将颜色直接定义在 `FoodCategory` 枚举中:
  ```kotlin
  enum class FoodCategory(val label: String, val iconColor: Color, val badgeTextColor: Color) {
      MEAL("正餐", Color(0xFFFFE0B2), Color(0xFFFF6F00)),
      ...
  }
  ```
  或用 `Map<FoodCategory, Pair<Color, Color>>` 集中配置。

#### 问题 3: 🟡 `item.effectDescription` 在 `nutrition != null` 时直接使用,未处理空字符串
- 位置: FoodItemCard.kt:128-135
- 问题描述:
  ```kotlin
  if (item.nutrition != null) {
      Spacer(modifier = Modifier.height(4.dp))
      Text(text = item.effectDescription, ...)
  }
  ```
  若 `nutrition` 非空但 `effectDescription` 为空字符串,会渲染一个空的 `Text` 和多余的 `Spacer`,占用 UI 空间。
- 建议方案: 加非空判断:`if (item.nutrition != null && item.effectDescription.isNotEmpty())`。

---

### food/FoodScreen.kt

#### 问题 1: 🔴 `LazyColumn` 内用 `forEach` 渲染食物列表,完全失去懒加载
- 位置: FoodScreen.kt:204-214
- 问题描述:
  ```kotlin
  else -> {
      Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
          shopUiState.filteredItems.forEach { item ->
              FoodItemCard(
                  item = item,
                  canAfford = shopUiState.balance.coins >= item.price,
                  onBuy = { onShowPurchaseConfirm(item) },
                  onEat = { onEatFood(item.id) }
              )
          }
      }
  }
  ```
  该代码位于 `LazyColumn` 的 `item { SectionCard { ... } }` 内部,所有食物卡片都在一个 `Column` 中一次性组合。当 `filteredItems` 较长(几十个)时:
  - 首屏渲染所有卡片,造成明显卡顿。
  - 滚动时 `LazyColumn` 无法回收屏幕外的卡片,内存与组合开销随列表线性增长。
  - `FoodItemCard` 中的 lambda(`onBuy`、`onEat`)在每次重组时都新建,且无 `key`,列表变化时状态可能错位。
- 建议方案: 重构为 `LazyColumn` 的 `items`:
  ```kotlin
  LazyColumn(...) {
      item { /* 余额 SectionCard */ }
      shopUiState.error?.let { item { /* 错误 SectionCard */ } }
      item { /* 食物菜单 SectionCard 头部 + 分类筛选 */ }
      itemsIndexed(shopUiState.filteredItems, key = { _, it -> it.id }) { _, item ->
          FoodItemCard(
              item = item,
              canAfford = shopUiState.balance.coins >= item.price,
              onBuy = { onShowPurchaseConfirm(item) },
              onEat = { onEatFood(item.id) }
          )
      }
  }
  ```
  注意:需把"食物菜单"的 `SectionCard` 拆分,头部作为单独 `item`,列表用 `items` 渲染。

#### 问题 2: 🟠 `LazyColumn` 内嵌 `LazyRow`(`CategoryFilterRow`)未指定高度或 key
- 位置: FoodScreen.kt:184-187, 260-276
- 问题描述: `CategoryFilterRow` 在 `SectionCard` 内部(即 `LazyColumn` 的 `item` 内)使用 `LazyRow`。在嵌套场景下,`LazyRow` 的高度需要由内容驱动,通常没问题;但 `items(CATEGORY_OPTIONS)` 未传 `key`,且每个 `Surface` 的 `onClick` lambda 在重组时新建。
- 建议方案: `items(CATEGORY_OPTIONS, key = { it.first })` 添加 key;`onClick` lambda 可通过 `remember` 缓存或提升到外部。

#### 问题 3: 🟠 `Spacer(modifier = Modifier.size(8.dp))` 语义混淆
- 位置: FoodScreen.kt:148, 393
- 问题描述: `Modifier.size(8.dp)` 会同时约束宽度和高度为 8dp,在 `Row` 中作为 `Spacer` 用时,实际效果是宽度 8dp,但语义不清晰。其他地方用的是 `Modifier.width(8.dp)` 或 `Modifier.height(8.dp)`。
- 建议方案: 在 `Row` 中用 `Spacer(modifier = Modifier.width(8.dp))`,在 `Column` 中用 `Spacer(modifier = Modifier.height(8.dp))`,保持语义明确。

#### 问题 4: 🟡 错误提示仅在 `LazyColumn` 内作为 `item` 渲染,滚动后不可见
- 位置: FoodScreen.kt:166-174
- 问题描述: 错误信息作为 `LazyColumn` 的第一个 `item`(在余额之后),用户向下滚动浏览食物时,错误提示会滚出视野,无法及时清除或感知。
- 建议方案: 错误提示应固定在顶部(如 `ModuleHeader` 下方),或用 `Snackbar` 展示,避免被滚动隐藏。

#### 问题 5: 🟡 硬编码颜色 `Color(0xFFFFD700)`
- 位置: FoodScreen.kt:145, 392
- 问题描述: 金币图标颜色 `Color(0xFFFFD700)` 重复硬编码,与 `FoodItemCard` 中的同色值未统一管理。
- 建议方案: 提取为 `val CoinGold = Color(0xFFFFD700)` 放到 `theme/` 包,或用 `MaterialTheme.colorScheme`。

---

### shop/ShopViewModel.kt

#### 问题 1: 🔴 `ShopUiState` 包含大量 UI 临时状态,职责过重
- 位置: ShopViewModel.kt:32-68
- 问题描述: `ShopUiState` 同时承载:
  - 数据状态:`items`、`balance`、`selectedCategory`、`isLoading`、`error`
  - UI 交互状态:`showPurchaseConfirm`、`itemToPurchase`、`purchaseQuantity`、`showPurchaseResult`、`purchaseResult`
  
  后者属于 UI 交互的临时状态(对话框显隐、数量选择),混入 UiState 导致:
  - 任何 UI 交互(如点开对话框)都会触发整个 `ShopUiState` 的 copy,进而触发所有订阅该 StateFlow 的 Composable 重组。
  - ViewModel 难以测试(测试购买流程需要 mock 多个 UI 状态)。
  - 状态流转复杂,容易出 bug(如 `confirmPurchase` 成功后要同时清空 `itemToPurchase`、重置 `quantity`、设置 `purchaseResult`、显示 `showPurchaseResult`)。
- 建议方案: 拆分状态:
  - `ShopUiState`:只保留 `items`、`balance`、`selectedCategory`、`isLoading`、`error`。
  - 购买流程用单独的 `PurchaseDialogState` sealed class 或独立 StateFlow 管理:
    ```kotlin
    sealed class PurchaseDialogState {
        object Hidden : PurchaseDialogState()
        data class Confirming(val item: ShopItem, val quantity: Int) : PurchaseDialogState()
        data class Result(val result: PurchaseResult) : PurchaseDialogState()
    }
    ```

#### 问题 2: 🟠 `confirmPurchase` 与 `loadItems` 均无防重入保护
- 位置: ShopViewModel.kt:96-120, 184-219
- 问题描述:
  - `loadItems()`:快速连续调用会发起多个并发请求,后到的请求可能覆盖先到的结果(竞态)。
  - `confirmPurchase()`:用户快速双击"确认购买",会发起两次购买请求,可能造成重复扣款或库存错误。
  - 两者都只设了 `isLoading = true`,但没有用 `isLoading` 做守卫(`if (_uiState.value.isLoading) return`)。
- 建议方案: 加入防重入:
  ```kotlin
  fun loadItems() {
      if (_uiState.value.isLoading) return
      viewModelScope.launch { ... }
  }
  fun confirmPurchase() {
      if (_uiState.value.isLoading) return
      ...
  }
  ```
  或用 `Job` 跟踪并取消上一个请求。

#### 问题 3: 🟠 `increaseQuantity` 在余额不足时会让 `quantity` 变为 0
- 位置: ShopViewModel.kt:158-168
- 问题描述:
  ```kotlin
  val maxQuantity = _uiState.value.itemToPurchase?.let { item ->
      _uiState.value.balance.coins / item.price
  } ?: 1
  _uiState.update {
      it.copy(purchaseQuantity = minOf(it.purchaseQuantity + 1, maxQuantity, 99))
  }
  ```
  若 `balance.coins < item.price`(余额买不起一个),`maxQuantity = 0`。用户点"+",`quantity` 从 1 变成 `minOf(2, 0, 99) = 0`。此时:
  - `canAffordSelectedItem = balance.coins >= item.price * 0 = balance >= 0 = true`(只要余额非负就成立)。
  - UI 显示"确认购买"按钮可点击,`totalCost = 0`。
  - 用户点击确认会发起 `purchaseItem(item.id, 0)` 调用,后端行为未知,但 UI 上明显是误导。
- 建议方案: 增加最小值保护,且 `canAffordSelectedItem` 应考虑 `quantity > 0`:
  ```kotlin
  _uiState.update {
      val newQty = (it.purchaseQuantity + 1).coerceAtMost(maxQuantity.coerceAtLeast(1)).coerceAtMost(99)
      it.copy(purchaseQuantity = newQty)
  }
  ```
  并修改 `canAffordSelectedItem`:
  ```kotlin
  val canAffordSelectedItem: Boolean
      get() = purchaseQuantity > 0 && itemToPurchase?.let { item ->
          balance.coins >= item.price * purchaseQuantity
      } ?: false
  ```

#### 问题 4: 🟠 `confirmPurchase` 失败时直接关闭对话框,不展示结果
- 位置: ShopViewModel.kt:207-216
- 问题描述: 购买失败时,`showPurchaseConfirm = false`、`itemToPurchase = null`,只设置 `error` 字段。但购买成功时,会弹出 `PurchaseResultDialog`。失败与成功的 UX 不一致:用户看不到失败结果对话框,只能注意到顶部 error 提示(若 error 提示在 LazyColumn 内被滚动隐藏,则更糟)。
- 建议方案: 失败也走 `PurchaseResult` 流程:
  ```kotlin
  onFailure = { e ->
      _uiState.update {
          it.copy(
              isLoading = false,
              showPurchaseConfirm = false,
              itemToPurchase = null,
              purchaseResult = PurchaseResult(success = false, message = "购买失败: ${e.message}", newBalance = null),
              showPurchaseResult = true
          )
      }
  }
  ```

#### 问题 5: 🟠 `mealItems` / `snackItems` / `drinkItems` 是死代码
- 位置: ShopViewModel.kt:52-59
- 问题描述: `ShopUiState` 中定义了 `mealItems`、`snackItems`、`drinkItems` 三个计算属性,但 `FoodScreen` 只使用 `filteredItems`,这三个属性从未被引用。注释"与Web端对齐"暗示是历史遗留代码。
- 建议方案: 删除这三个属性,减少维护成本。

#### 问题 6: 🟡 `error` 字段无自动清除机制
- 位置: ShopViewModel.kt:36, 115, 213, 237
- 问题描述: `error` 只能由用户点击"清除"按钮(在 FoodScreen 中)主动清除。若用户忽略错误,`error` 会一直保留在 UiState 中,后续刷新成功后 `loadItems` 会设 `error = null`,但 `confirmPurchase` 失败后不清空。可能导致错误提示残留。
- 建议方案: 错误展示后用 `viewModelScope.launch { delay(3000); clearError() }` 自动清除,或用 `SharedFlow` 发送一次性事件。

#### 问题 7: 🟡 `init { loadItems() }` 失败后无重试机制
- 位置: ShopViewModel.kt:89-91
- 问题描述: 首次加载失败时,`error` 被设置,但用户需手动点击刷新。无指数退避重试或占位重试 UI。
- 建议方案: 至少在 UI 层提供"重试"按钮(`EmptyFoodState` 改为根据 `error` 区分"无数据"与"加载失败",失败时显示重试按钮)。

---

### status/StatusViewModel.kt

#### 问题 1: 🔴 同时注入 `StatusRepository` 接口与 `StatusRepositoryImpl` 实现类,违反依赖倒置
- 位置: StatusViewModel.kt:91-96
- 问题描述:
  ```kotlin
  @HiltViewModel
  class StatusViewModel @Inject constructor(
      private val statusRepository: StatusRepository,
      private val statusRepositoryImpl: StatusRepositoryImpl,
      private val toolsRepository: ToolsRepository,
      private val webSocketManager: WebSocketManager
  ) : ViewModel()
  ```
  - `StatusRepository` 是接口,`StatusRepositoryImpl` 是其实现类。同时注入两者违反了依赖倒置原则(DIP)。
  - `loadStatus()` 调用 `statusRepository.getLifeStatus()`,`refreshStatus()` 调用 `statusRepositoryImpl.forceRefreshLifeStatus()`——同一个 ViewModel 用两个不同引用操作"同一类"依赖,意图混乱。
  - 测试时需要 mock 两个对象,且 `StatusRepositoryImpl` 是具体类,mock 困难。
- 建议方案:
  - 若 `forceRefreshLifeStatus()` 是 `StatusRepository` 接口缺失的方法,应将其加入接口,只注入 `StatusRepository`。
  - 若 `StatusRepositoryImpl` 有接口之外的能力,应抽象出新的接口(如 `StatusRefreshable`),ViewModel 依赖新接口。
  - 修正后只保留一个 `StatusRepository` 注入。

#### 问题 2: 🔴 `ReconnectSync` 中 `health` 错误地用 `status["energy"]` 赋值
- 位置: StatusViewModel.kt:226-232
- 问题描述:
  ```kotlin
  val syncedLifeStatus = com.aveline.ai.mobile.domain.models.LifeStatus(
      health = status["energy"] ?: 1.0f,      // ← 用了 energy 字段
      hunger = status["hunger"] ?: 0f,
      happiness = status["mood_score"] ?: 1.0f,
      energy = status["energy"] ?: 1.0f,
      timestamp = System.currentTimeMillis()
  )
  ```
  `health` 字段读的是 `status["energy"]`,与 `energy` 字段同源。这会导致重连后 UI 上"健康"和"能量"显示相同的值,健康数据丢失。看起来是复制粘贴错误。
- 建议方案: 改为 `health = status["health"] ?: 1.0f`,并与后端确认字段名。同时 `hunger = status["hunger"] ?: 0f` 默认 0f 表示完全饥饿,可能不合理,建议默认 `1.0f`(饱腹)或 `0.5f`。

#### 问题 3: 🟠 多个 collector 未保存 Job 引用,且 `onCleared` 取消不完整
- 位置: StatusViewModel.kt:189-240
- 问题描述:
  - `observeConnection()` 内 `viewModelScope.launch { webSocketManager.connectionState.collect ... }` 未保存 Job。
  - `observeEmotion()` 内有两个协程:第一个保存为 `emotionJob`,第二个(`webSocketManager.messages.collect`)未保存。
  - `onCleared()` 只取消了 `clockJob` 和 `emotionJob`,其他协程依赖 `viewModelScope` 取消传播。
  - 代码不一致(有的保存有的不保存),可维护性差。
- 建议方案: 统一保存所有 Job,或在 `onCleared` 中调用 `viewModelScope.cancel()`(其实 `ViewModel` 的 `viewModelScope` 在 `onCleared` 时会自动取消,所以手动 cancel 是冗余的——但既然写了,就该写全)。建议删除 `onCleared` 中手动 cancel(`viewModelScope` 会处理),或把所有 Job 都保存并统一取消。

#### 问题 4: 🟠 `loadSystemStats` 是 fire-and-forget,且 `loadStatus`/`refreshStatus` 内部嵌套 launch
- 位置: StatusViewModel.kt:139, 171, 175-184
- 问题描述:
  ```kotlin
  fun loadStatus() {
      viewModelScope.launch {
          ... result.fold(...)  // 这里同步处理
          loadSystemStats()      // 调用另一个函数
      }
  }
  
  private fun loadSystemStats() {
      viewModelScope.launch {   // ← 又开一个协程
          toolsRepository.getSystemStats()...
      }
  }
  ```
  - `loadSystemStats` 内部又 `launch`,导致它返回后外层协程立即结束,`loadSystemStats` 的协程独立运行。
  - `loadSystemStats` 的 `onFailure { // 保持安静失败 }` 完全吞异常,UI 无法感知 system stats 加载失败。
  - 若 `loadStatus` 频繁调用(如重连时),会有多个 `loadSystemStats` 协程并发。
- 建议方案:
  - 让 `loadSystemStats` 不自己 launch,改为 suspend 函数,由调用方决定:
    ```kotlin
    private suspend fun loadSystemStats() {
        toolsRepository.getSystemStats().onSuccess { ... }.onFailure { e ->
            // 至少 log,或更新一个独立的 systemStatsError 字段
            Log.w("StatusViewModel", "loadSystemStats failed", e)
        }
    }
    ```
  - 在 `loadStatus` 的 `fold` 后直接 `loadSystemStats()`(无需再 launch)。

#### 问题 5: 🟠 `loadStatus` 与 `refreshStatus` 重复代码
- 位置: StatusViewModel.kt:114-173
- 问题描述: 两个函数结构几乎一致(更新 isLoading → 调用 repository → fold 处理 → loadSystemStats),仅调用的方法不同(`getLifeStatus()` vs `forceRefreshLifeStatus()`)。
- 建议方案: 抽取公共逻辑:
  ```kotlin
  private suspend fun fetchStatus(useForce: Boolean) {
      _uiState.update { it.copy(isLoading = true, error = null) }
      val result = if (useForce) statusRepositoryImpl.forceRefreshLifeStatus()
                   else statusRepository.getLifeStatus()
      result.fold(
          onSuccess = { status -> _uiState.update { it.copy(lifeStatus = status, isLoading = false) } },
          onFailure = { e -> _uiState.update { it.copy(isLoading = false, error = "${if (useForce) "刷新" else "加载"}失败: ${e.message}") } }
      )
      loadSystemStats()
  }
  fun loadStatus() { viewModelScope.launch { fetchStatus(false) } }
  fun refreshStatus() { viewModelScope.launch { fetchStatus(true) } }
  ```

#### 问题 6: 🟠 `emotionMix: Map<String, Float>` 是不稳定类型,导致重组
- 位置: StatusViewModel.kt:38
- 问题描述: `Map<String, Float>` 是 Kotlin 内建接口,Compose 编译器视为不稳定类型。每次 `emotionMix` 更新(即使内容相同)都会触发订阅该字段的 Composable 重组。WebSocket 推送的 `EmotionUpdate` 频率可能较高,导致不必要的重组开销。
- 建议方案:
  - 用 `@Immutable data class EmotionMix(val values: Map<String, Float>)` 包装,或
  - 改用 `kotlinx.collections.immutable` 的 `ImmutableMap<String, Float>`。

#### 问题 7: 🟠 `startClock` 每秒更新 StateFlow,触发全局重组
- 位置: StatusViewModel.kt:245-256
- 问题描述:
  ```kotlin
  while (true) {
      ...
      _uiState.update { it.copy(clock = formatted) }
      delay(1000)
  }
  ```
  每秒更新 `_uiState`,所有订阅 `uiState` 的 Composable(包括不显示时钟的组件)都会每秒重组。这是性能浪费。
- 建议方案: 把 `clock` 拆到独立的 `StateFlow<String>`:
  ```kotlin
  private val _clock = MutableStateFlow("")
  val clock: StateFlow<String> = _clock.asStateFlow()
  ```
  UI 中只订阅 `clock` 的组件会重组,其他组件不受影响。

#### 问题 8: 🟡 `Log.d` 调用未用 `BuildConfig.DEBUG` 守卫
- 位置: StatusViewModel.kt:218, 223
- 问题描述: `Log.d("StatusViewModel", ...)` 在 release 包中也会执行,泄漏日志信息且有轻微性能开销。
- 建议方案: 用 `if (BuildConfig.DEBUG) Log.d(...)` 包裹,或引入 Timber(`Timber.d(...)`,自动在 release 关闭)。

---

### health/DailyDataViewModel.kt

#### 问题 1: 🔴 JSON 解析逻辑混入 ViewModel,职责过重
- 位置: DailyDataViewModel.kt:89-159
- 问题描述: `refreshData()` 内部有大量 JSON 解析代码:
  ```kotlin
  val portrait = healthRepository.getDailyPortraitToday().getOrThrow()
  val portraitData = portrait["portrait"]?.jsonObject ?: JsonObject(emptyMap())
  val schedule = portraitData["schedule"]?.jsonObject
  ...
  val sessions = study?.get("sessions")?.jsonArray.orEmptyArray().map { item ->
      val obj = item.jsonObject
      DailyStudySession(
          topic = obj.string("topic"),
          ...
      )
  }
  ```
  - ViewModel 应只协调 Repository 与 UiState,不应处理 JSON 解析。这是 Repository 或 Mapper 层的职责。
  - 解析逻辑复杂(约 50 行),且 `refreshData` 本身已经 70 行,可读性差。
  - 解析逻辑无法单独测试(必须 mock `healthRepository` 返回特定 JSON)。
  - 若后端字段变化,需改 ViewModel 而非 Repository。
- 建议方案:
  - 在 Repository 层返回领域对象(如 `DailyPortrait`),而非 `JsonObject`:
    ```kotlin
    data class DailyPortrait(
        val date: String,
        val schedule: DailySchedule?,
        val drink: DailyDrink?,
        val study: DailyStudy?,
        val meals: List<DailyMeal>,
        ...
    )
    ```
  - Repository 内部完成 JSON → 领域对象的映射。
  - ViewModel 只做 `val portrait = healthRepository.getDailyPortraitToday(); _uiState.update { it.copy(...portrait) }`。

#### 问题 2: 🔴 `recordDrink(units: Int)` 参数语义与 `LifeWaterTab.onQuickDrink(ml: Int)` 调用不匹配
- 位置: DailyDataViewModel.kt:161-179
- 问题描述:
  - `LifeWaterTab` 的 `onQuickDrink` 回调传入 200/300/500(注释明确为"毫升数"),见 LifeWaterTab.kt:37, 77-79。
  - `DailyDataViewModel.recordDrink(units: Int = 1)` 接收 `units` 参数,并 `put("units", units)` 传给后端。
  - 若父级把 `onQuickDrink` 直接接到 `recordDrink`(常见接法),则 `recordDrink(200)` 会向后端发送 `{"units": 200}`,后端可能解释为 200 杯/单位,远超用户意图(200ml)。
  - 这是数据正确性 bug,会导致饮水记录严重错误。
- 建议方案:
  - 统一参数语义:若后端接收 ml,`recordDrink` 应改名为 `recordDrinkMl(ml: Int)`,内部 `put("ml", ml)`。
  - 若后端接收 units(杯数),`LifeWaterTab` 的 `onQuickDrink` 应改为传杯数(如 1/2/3),而非 ml。
  - 在未确认后端契约前,至少在 `recordDrink` 内做单位换算(如 `put("units", ml / 250)` 假设 250ml/杯)。

#### 问题 3: 🟠 `refreshData` 无防重入保护,可能并发竞态
- 位置: DailyDataViewModel.kt:89-159
- 问题描述: `refreshData` 在 `init` 中调用,且 `recordDrink`/`startStudy`/`finishStudy` 成功后都会调用 `refreshData`。若用户快速操作(喝水 → 立即开始学习),两个 `refreshData` 会并发,后到的可能覆盖先到的结果(因为 `lastRefreshTime` 也会被覆盖)。
- 建议方案: 用 `Job` 跟踪并取消上一个:
  ```kotlin
  private var refreshJob: Job? = null
  fun refreshData() {
      refreshJob?.cancel()
      refreshJob = viewModelScope.launch { ... }
  }
  ```

#### 问题 4: 🟠 `startStudy` / `finishStudy` / `recordDrink` 在成功后调用 `refreshData`,但 `isLoading` 状态流转不清晰
- 位置: DailyDataViewModel.kt:163-178, 181-205, 207-221
- 问题描述: 以 `recordDrink` 为例:
  ```kotlin
  _uiState.update { it.copy(isLoading = true, ...) }  // 1. 设 true
  healthRepository.recordDailyDrink(...).onSuccess { response ->
      _uiState.update { it.copy(message = ...) }  // 2. 未设 isLoading
      refreshData()  // 3. refreshData 内部设 true,完成后设 false
  }.onFailure { error ->
      _uiState.update { it.copy(isLoading = false, ...) }  // 4. 失败设 false
  }
  ```
  成功路径中,步骤 2 没设 `isLoading = false`,直接进入步骤 3。若 `refreshData` 抛出未捕获异常(虽然有 runCatching),`isLoading` 会卡在 true。虽然当前代码 `refreshData` 内有 `runCatching` 兜底,但状态流转依赖隐式时序,脆弱。
- 建议方案: 在 `onSuccess` 显式设置 `isLoading = false`,或把"操作成功 + 刷新"封装为单一 suspend 函数,统一管理 isLoading。

#### 问题 5: 🟡 `lastRefreshTime` 在 data class 默认值中调用 `System.currentTimeMillis()`
- 位置: DailyDataViewModel.kt:57
- 问题描述: `val lastRefreshTime: Long = System.currentTimeMillis()` 作为默认值,每次创建默认 `DailyDataUiState()`(如首次初始化)都会捕获当前时间。这在单元测试中不可预测(无法 mock 时间),且若该默认值被意外使用,可能导致"未刷新但有刷新时间"的假象。
- 建议方案: 默认值改为 `0L`,在 `refreshData` 成功时再设实际时间:
  ```kotlin
  val lastRefreshTime: Long = 0L
  ```

#### 问题 6: 🟡 JSON 扩展函数 `string` 等对缺失字段返回空字符串,隐藏数据问题
- 位置: DailyDataViewModel.kt:228-246
- 问题描述: `JsonObject.string(key)` 在 key 不存在或类型不匹配时返回 `""`(空字符串)。`DailyStudySession(topic = obj.string("topic"))` 若后端漏返 `topic`,会静默得到空字符串,UI 显示"学习"(因 `topic.ifBlank { "学习" }`)。这掩盖了数据问题,排错困难。
- 建议方案: 至少在解析失败时 log 警告:
  ```kotlin
  private fun JsonObject.string(key: String): String {
      return this[key]?.jsonPrimitive?.contentOrNull.also {
          if (it == null) Log.w("DailyData", "Missing field: $key")
      }?.orEmpty() ?: ""
  }
  ```
  或返回 `String?`,由调用方决定默认值。

---

## 总结与优先级建议

### 必须立即修复(🔴 严重)

1. **`FoodScreen.kt:204-214`** — LazyColumn 内用 forEach 渲染食物列表,列表长时严重卡顿。重构为 `items()` 懒加载。
2. **`ShopViewModel.kt:32-68`** — ShopUiState 混入 UI 临时状态,拆分数据状态与交互状态。
3. **`StatusViewModel.kt:91-96`** — 同时注入接口与实现类,违反 DIP,统一为单一接口注入。
4. **`StatusViewModel.kt:226-232`** — `ReconnectSync` 中 `health = status["energy"]` 是 bug,改为 `status["health"]`。
5. **`DailyDataViewModel.kt:89-159`** — JSON 解析下沉到 Repository/Mapper,ViewModel 只协调。
6. **`DailyDataViewModel.kt:161-179`** — `recordDrink(units)` 与 UI 传 ml 不匹配,统一单位语义。

### 建议尽快处理(🟠 中等)

7. `ShopViewModel.kt:184-219` — `confirmPurchase` 与 `loadItems` 加防重入保护。
8. `ShopViewModel.kt:158-168` — `increaseQuantity` 加最小值保护,避免 quantity=0。
9. `ShopViewModel.kt:207-216` — 购买失败也走结果对话框,统一 UX。
10. `ShopViewModel.kt:52-59` — 删除死代码 `mealItems/snackItems/drinkItems`。
11. `StatusViewModel.kt:175-184` — `loadSystemStats` 改 suspend,避免 fire-and-forget。
12. `StatusViewModel.kt:114-173` — `loadStatus` 与 `refreshStatus` 抽取公共逻辑。
13. `StatusViewModel.kt:245-256` — `clock` 拆为独立 StateFlow,避免全局重组。
14. `StatusViewModel.kt:38` — `emotionMix` 用 `@Immutable` 包装或 `ImmutableMap`。
15. `StatusViewModel.kt:189-240` — 统一保存所有 collector Job 或删除冗余的 onCleared 手动取消。
16. `LifeScreen.kt:196-253` — 4 个 Tab 内容抽取公共 `LifeTabPage`。
17. `LifeScreen.kt:92-94` — `LaunchedEffect` 跳过首次发射,避免多余 onTabChange。
18. `LifeScreen.kt:183-255` — 用 `SaveableStateProvider` 保存远端 Tab 滚动状态。
19. `LifeMealTab.kt:72-76` / `LifeScheduleTab.kt:79-83` — forEach 加 key 或改 LazyColumn。
20. `LifeWaterTab.kt:29` — `WATER_GOAL_ML` 改为可配置。
21. `LifeScheduleTab.kt:130-135` — `SimpleDateFormat` 改 `java.time` API。
22. `FoodItemCard.kt:65,145,155` — 硬编码颜色提取到主题。
23. `DailyDataViewModel.kt:89-159` — `refreshData` 加防重入(Job 取消旧请求)。

### 可选优化(🟡 轻微)

24. 多文件删除未使用的 `Color`/`remember` 导入。
25. `LifeMealTab.kt:104-110` — OutlinedTextField 加 KeyboardOptions/ImeAction。
26. `FoodScreen.kt:148,393` — `Spacer.size` 改为语义明确的 `width`/`height`。
27. `FoodScreen.kt:166-174` — 错误提示固定在顶部或用 Snackbar。
28. `StatusViewModel.kt:218,223` — `Log.d` 用 `BuildConfig.DEBUG` 守卫或换 Timber。
29. `DailyDataViewModel.kt:57` — `lastRefreshTime` 默认值改 `0L`。
30. `DailyDataViewModel.kt:228-246` — JSON 解析失败时 log 警告。
31. `FoodItemCard.kt:128-135` — `effectDescription` 加非空判断。
32. `ShopViewModel.kt:36` — `error` 加自动清除机制。
33. `ShopViewModel.kt:89-91` — `init` 加载失败提供重试 UI。
34. `FoodItemCard.kt:202-213` — `FoodCategory` 颜色内聚到枚举属性。

### 架构层面改进建议

1. **状态管理规范化**:整个项目的 ViewModel 普遍把"UI 交互状态"(对话框显隐、选中项)和"数据状态"混在一个 UiState 中。建议制定规范:数据状态走 `StateFlow<UiState>`,一次性事件(导航、 Snackbar、错误提示)走 `SharedFlow<UiEvent>`。

2. **Repository 返回类型**:Repository 不应返回 `JsonObject` 让 ViewModel 解析,应返回领域对象。`HealthRepository.getDailyPortraitToday()` 返回 `JsonObject` 是反模式,应在 Repository 内部完成映射。

3. **依赖注入审查**:`StatusViewModel` 同时注入 `StatusRepository` 和 `StatusRepositoryImpl` 暴露了 DI 配置问题,建议审查项目内其他 ViewModel 是否有类似情况。

4. **Compose 稳定性**:项目中对 `Map`、`List` 等不稳定类型的使用较随意,建议引入 `kotlinx.collections.immutable` 或统一用 `@Immutable` 注解包装,减少不必要重组。
