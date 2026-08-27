package com.aveline.ai.mobile.presentation.persona

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
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
    val error: String? = null
)

@HiltViewModel
class PersonaViewModel @Inject constructor(
    private val personaRepository: PersonaRepository
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
                val activeRes = personaRepository.getActivePersonaRaw().getOrThrow()
                val filename = try { activeRes["filename"]?.jsonPrimitive?.content } catch (_: Exception) { null }
                    ?: try { activeRes["data"]?.jsonObject?.get("filename")?.jsonPrimitive?.content } catch (_: Exception) { null }
                    ?: ""
                _uiState.update {
                    it.copy(
                        personas = personas,
                        activePersona = activeRes,
                        activeFilename = filename,
                        isLoading = false
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

    fun switchPersona(filename: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isSwitching = true) }
            runCatching {
                personaRepository.selectPersona(filename).getOrThrow()
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
