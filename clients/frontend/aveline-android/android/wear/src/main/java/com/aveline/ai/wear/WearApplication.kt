package com.aveline.ai.wear

import android.app.Application

/**
 * Wear OS 应用入口。
 *
 * 目前只做轻量级初始化,数据采集逻辑交给 [HealthCollectService]。
 */
class WearApplication : Application()
