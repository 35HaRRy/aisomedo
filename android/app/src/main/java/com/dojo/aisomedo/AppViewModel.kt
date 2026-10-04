package com.dojo.aisomedo

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.OkHttpClient
import java.net.URI

enum class Phase { ADDRESS, LOADING, PAIRING, READY, UPDATE_REQUIRED, CONNECTION_ERROR }
enum class Destination { DASHBOARD, PACKAGE, ACTIVITY, SETTINGS }
enum class UiIssue { INVALID_SERVER, NETWORK, INVALID_CODE, RATE_LIMIT, INVALID_INPUT, PROVIDER_UNAVAILABLE, POLICY_MISSING, POLICY_CHANGED, STORAGE, UNKNOWN }

data class AppUiState(
    val phase: Phase = Phase.ADDRESS,
    val origin: String = "",
    val client: ClientOut? = null,
    val compat: CompatInfo? = null,
    val dashboard: DashboardOut? = null,
    val setup: SetupOut? = null,
    val destination: Destination = Destination.DASHBOARD,
    val step: String? = null,
    val busy: Boolean = false,
    val stale: Boolean = false,
    val issue: UiIssue? = null,
    val updateUrl: String? = null,
)

class AppViewModel(
    private val store: SessionStore,
    private val http: OkHttpClient,
    private val versionCode: Int,
    private val allowHttp: Boolean,
    val saved: SavedStateHandle,
) : ViewModel() {
    private val mutable = MutableStateFlow(AppUiState())
    val state = mutable.asStateFlow()
    private var token: String? = null
    private var generation = 0
    private var job: Job? = null
    private var prompted = false

    init {
        try { mutable.update { it.copy(origin = store.origin.orEmpty()) } }
        catch (_: Exception) { mutable.update { it.copy(issue = UiIssue.STORAGE) } }
        refresh()
    }

    private fun api() = DojoApi(state.value.origin, token, versionCode, http)
    private fun launch(pairing: Boolean = false, action: suspend (Int) -> Unit) {
        if (state.value.busy) return
        val current = generation
        mutable.update { it.copy(busy = true, issue = null) }
        job = viewModelScope.launch {
            try { action(current) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (generation == current) failure(e, pairing) }
            finally { if (generation == current) mutable.update { it.copy(busy = false) } }
        }
    }

    fun submitOrigin(raw: String) {
        if (state.value.busy) return
        val origin = try { ApiConfig.normalizeOrigin(raw, allowHttp) }
        catch (_: Exception) { mutable.update { it.copy(issue = UiIssue.INVALID_SERVER) }; return }
        launch {
            withContext(Dispatchers.IO) { store.setOrigin(origin) }
            token = null
            mutable.value = AppUiState(origin = origin, busy = true)
            boot(it)
        }
    }

    fun refresh() {
        if (state.value.origin.isBlank()) return
        launch { current -> boot(current) }
    }

    private suspend fun boot(current: Int) {
        val previous = state.value
        val origin = ApiConfig.normalizeOrigin(previous.origin, allowHttp)
        if (previous.client == null || previous.phase == Phase.UPDATE_REQUIRED) mutable.update { it.copy(phase = Phase.LOADING) }
        val compat = DojoApi(origin, null, versionCode, http).compat()
        require(compat.androidMinVersionCode >= 1 && compat.androidCurrentVersionCode >= compat.androidMinVersionCode)
        if (generation != current) return
        mutable.update { it.copy(compat = compat, updateUrl = safeExternalUrl(compat.updateUrl)) }
        if (UpdatePolicy.isOutdated(versionCode, compat.androidMinVersionCode)) {
            mutable.update { it.copy(phase = Phase.UPDATE_REQUIRED) }; return
        }
        token = try { withContext(Dispatchers.IO) { store.readToken(origin) } }
        catch (_: CredentialUnavailable) {
            withContext(Dispatchers.IO) { store.clearToken() }
            mutable.update { it.copy(issue = UiIssue.STORAGE) }; null
        }
        if (generation != current) return
        if (token == null) { mutable.update { it.copy(phase = Phase.PAIRING) }; return }
        authenticated(current)
    }

    fun pair(code: String, name: String) {
        if (state.value.phase != Phase.PAIRING) return
        if (code.isBlank() || name.isBlank()) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        launch(pairing = true) { current ->
            val result = api().pair(code.trim(), name.trim())
            val credential = result.token
            require(result.kind == "device" && !credential.isNullOrBlank())
            if (generation != current) return@launch
            withContext(Dispatchers.IO) { store.saveToken(state.value.origin, credential) }
            if (generation != current) return@launch
            token = credential
            // A 401 after validation is revocation, not a rejected pairing code.
            try { authenticated(current) }
            catch (e: ApiFailure) { failure(e, false) }
        }
    }

    private suspend fun authenticated(current: Int) {
        val client = api().me()
        if (client.kind != "device" || client.revokedAt != null) throw ApiFailure(401)
        if (generation != current) return
        mutable.update { it.copy(client = client) }
        val setup = api().setup()
        val dashboard = api().dashboard()
        if (generation != current) return
        var step = state.value.step
        if (!prompted) {
            prompted = true
            step = saved.get<String>("step") ?: if (!setup.ready) setup.checklist.firstOrNull { it.required && !it.complete }?.key else null
        }
        val destination = Destination.entries.firstOrNull { it.name == saved.get<String>("destination") } ?: state.value.destination
        mutable.update { it.copy(phase = Phase.READY, client = client, setup = setup, dashboard = dashboard, step = step, destination = destination, stale = false) }
    }

    private fun failure(error: Exception, pairing: Boolean = false) {
        when {
            error is ApiFailure && error.status == 426 -> mutable.update { it.copy(phase = Phase.UPDATE_REQUIRED, updateUrl = safeExternalUrl(error.updateUrl.orEmpty()) ?: it.updateUrl) }
            error is ApiFailure && error.status == 401 && !pairing -> {
                generation++; token = null; prompted = false; clearSaved()
                val issue = try { store.clearToken(); null } catch (_: Exception) { UiIssue.STORAGE }
                mutable.value = AppUiState(origin = state.value.origin, compat = state.value.compat, phase = Phase.PAIRING, issue = issue)
            }
            else -> {
                val issue = when {
                    error is CredentialUnavailable -> UiIssue.STORAGE
                    error is ApiFailure && error.status == 401 -> UiIssue.INVALID_CODE
                    error is ApiFailure && error.status == 429 -> UiIssue.RATE_LIMIT
                    error is ApiFailure && error.status == 0 -> UiIssue.NETWORK
                    error is ApiFailure && error.status == 422 -> UiIssue.INVALID_INPUT
                    error is ApiFailure && error.status in 502..503 -> UiIssue.PROVIDER_UNAVAILABLE
                    else -> UiIssue.UNKNOWN
                }
                mutable.update { it.copy(issue = issue, stale = it.dashboard != null, phase = if (it.phase == Phase.LOADING) Phase.CONNECTION_ERROR else it.phase) }
            }
        }
    }

    fun changeServer() {
        generation++; job?.cancel(); token = null; prompted = false; clearSaved()
        val issue = try { store.setOrigin(""); null } catch (_: Exception) { UiIssue.STORAGE }
        mutable.value = AppUiState(issue = issue)
    }
    private fun clearSaved() { saved.keys().toList().forEach { saved.remove<Any>(it) } }
    fun navigate(destination: Destination) {
        if (state.value.phase != Phase.READY) return
        saved["destination"] = destination.name
        closeSetup(); mutable.update { it.copy(destination = destination) }
    }
    fun openSetup() {
        if (state.value.phase != Phase.READY) return
        selectStep(state.value.setup?.checklist?.firstOrNull { it.required && !it.complete }?.key ?: "pairing")
    }
    fun closeSetup() { saved.remove<String>("step"); mutable.update { it.copy(step = null) } }
    fun selectStep(key: String) {
        if (state.value.phase != Phase.READY) return
        saved["step"] = key; mutable.update { it.copy(step = key) }
    }
}

fun safeExternalUrl(raw: String): String? = try {
    val uri = URI(raw)
    raw.takeIf { uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null }
} catch (_: Exception) { null }
