package com.aveline.ai.mobile.presentation.persona

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

data class PersonaUiState(
    val personas: JsonArray = JsonArray(emptyList()),
    val activePersona: JsonObject? = null,
    val activeFilename: String = "",
    val isLoading: Boolean = false,
    val isSwitching: Boolean = false,
    val error: String? = null,
    /** 可选语音音色名（从 persona 响应的 default_voice 去重收集）。 */
    val voiceNames: List<String> = emptyList(),
    /** persona filename -> 后端下发的角色默认音色（default_voice）。 */
    val personaDefaultVoices: Map<String, String> = emptyMap(),
    /** persona filename -> 用户手选的音色名（本地覆盖，优先级最高）。 */
    val personaVoiceOverrides: Map<String, String> = emptyMap()
)

@HiltViewModel
class PersonaViewModel @Inject constructor(
    private val personaRepository: PersonaRepository,
    private val appPreferences: AppPreferences
) : ViewModel() {

    private val _uiState = MutableStateFlow(PersonaUiState())
    val uiState: StateFlow<PersonaUiState> = _uiState.asStateFlow()

    init {
        loadPersonas()
    }

    fun loadPersonas() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            runCatching {
                val personas = personaRepository.getPersonasRaw().getOrThrow()
                // 角色默认音色：从 persona 响应的 default_voice 取（用于显示"当前用哪个"）。
                val defaultVoices = mutableMapOf<String, String>()
                personas.forEach { element ->
                    runCatching {
                        val obj = element.jsonObject
                        val fn = obj["filename"]?.jsonPrimitive?.content ?: return@runCatching
                        val voice = obj["default_voice"]?.jsonPrimitive?.content.orEmpty()
                        if (voice.isNotBlank()) defaultVoices[fn] = voice
                    }
                }
                // 候选音色：用后端完整音色列表（voice_map 全部键，含未被角色引用的VoiceArtist等）；
                // 接口不可用时才回落到 persona 里出现过的 default_voice，避免列表全空。
                val apiVoices = runCatching {
                    personaRepository.getAvailableVoices().getOrThrow()
                }.onFailure {
                    android.util.Log.w("PersonaViewModel", "拉取音色列表失败: ${it.message}")
                }.getOrNull().orEmpty()
                val voiceCandidates = LinkedHashSet<String>(apiVoices)
                if (voiceCandidates.isEmpty()) voiceCandidates += defaultVoices.values
                val voiceOverrides = defaultVoices.keys
                    .mapNotNull { f -> appPreferences.getPersonaVoice(f)?.let { f to it } }
                    .toMap()
                val activeRes = personaRepository.getActivePersonaRaw().getOrThrow()
                val filename = try { activeRes["filename"]?.jsonPrimitive?.content } catch (_: Exception) { null }
                    ?: try { activeRes["data"]?.jsonObject?.get("filename")?.jsonPrimitive?.content } catch (_: Exception) { null }
                    ?: ""
                _uiState.update {
                    it.copy(
                        personas = personas,
                        activePersona = activeRes,
                        activeFilename = filename,
                        isLoading = false,
                        voiceNames = voiceCandidates.toList(),
                        personaDefaultVoices = defaultVoices,
                        personaVoiceOverrides = voiceOverrides
                    )
                }
            }.onFailure { e ->
                _uiState.update {
                    it.copy(
                        isLoading = false,
                        error = e.message ?: "加载失败"
                    )
                }
            }
        }
    }

    /**
     * 保存某角色的手选音色（传空串 = 恢复跟随角色默认音色）。
     *
     * 只写本地覆盖，TTS 下次播放即生效；手选值优先于后端下发的 default_voice。
     */
    fun selectVoice(filename: String, voiceName: String) {
        if (filename.isBlank()) return
        appPreferences.setPersonaVoice(filename, voiceName)
        _uiState.update { state ->
            val updated = state.personaVoiceOverrides.toMutableMap()
            if (voiceName.isBlank()) updated.remove(filename) else updated[filename] = voiceName
            state.copy(personaVoiceOverrides = updated)
        }
    }

    fun switchPersona(filename: String, onSelected: suspend (String) -> Unit = {}) {
        if (_uiState.value.isSwitching) return
        viewModelScope.launch {
            _uiState.update { it.copy(isSwitching = true) }
            runCatching {
                personaRepository.selectPersona(filename).getOrThrow()
                // 后端确认成功后才更新聊天归属和持久化选择，失败不显示虚假的高亮。
                onSelected(filename)
                val activeRes = personaRepository.getActivePersonaRaw().getOrThrow()
                _uiState.update {
                    it.copy(
                        isSwitching = false,
                        activePersona = activeRes,
                        activeFilename = filename
                    )
                }
            }.onFailure { e ->
                _uiState.update {
                    it.copy(
                        isSwitching = false,
                        error = e.message ?: "切换失败"
                    )
                }
            }
        }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}
