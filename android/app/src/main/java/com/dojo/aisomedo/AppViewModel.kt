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
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalTime
import kotlinx.serialization.json.*

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
    val plan: PlanOut? = null,
    val branding: BrandingDefaultsOut? = null,
    val consent: ConsentOut? = null,
    val instagram: StatusOut? = null,
    val attempt: AttemptOut? = null,
    val dirtySteps: Set<String> = emptySet(),
    val changedSteps: Set<String> = emptySet(),
    val drafts: Map<String, String> = emptyMap(),
    val consentAcknowledged: Boolean = false,
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
        mutable.update { it.copy(
            drafts = saved.keys().filter { key -> key.startsWith("draft_") }.associate { key -> key.removePrefix("draft_") to saved.get<String>(key).orEmpty() },
            dirtySteps = saved.get<ArrayList<String>>("dirty_steps")?.toSet().orEmpty(),
        ) }
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
        if (step != null) loadConfiguration(current)
    }

    private fun failure(error: Exception, pairing: Boolean = false) {
        if (error is PolicyChanged) return
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
        launch { loadConfiguration(it) }
    }

    fun markDirty(step: String) {
        mutable.update { it.copy(dirtySteps = it.dirtySteps + step) }
        saved["dirty_steps"] = ArrayList(state.value.dirtySteps)
    }
    fun setDraft(key: String, value: String, step: String) {
        if (state.value.phase != Phase.READY) return
        saved["draft_$key"] = value
        mutable.update { it.copy(drafts = it.drafts + (key to value)) }; markDirty(step)
    }
    private fun clean(step: String) {
        mutable.update { it.copy(dirtySteps = it.dirtySteps - step, changedSteps = it.changedSteps - step) }
        saved["dirty_steps"] = ArrayList(state.value.dirtySteps)
    }
    private fun remoteDrafts(step: String, values: Map<String, String>, changed: Boolean) {
        if (step in state.value.dirtySteps) {
            if (changed) mutable.update { it.copy(changedSteps = it.changedSteps + step) }
        } else {
            values.forEach { (key, value) -> saved["draft_$key"] = value }
            mutable.update { it.copy(drafts = it.drafts + values) }
        }
    }
    private suspend fun loadConfiguration(current: Int) {
        suspend fun load(action: suspend () -> Unit) {
            try { action() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (generation != current) return
                if (e is ApiFailure && (e.status == 401 || e.status == 426)) throw e
                if (e is ApiFailure && e.status == 404) {
                    mutable.update { it.copy(consent = null, consentAcknowledged = false, issue = UiIssue.POLICY_MISSING) }
                } else failure(e)
            }
        }
        load {
            val plan = api().plan()
            if (generation == current) {
                remoteDrafts("schedule", mapOf("date" to plan.anchorDate.orEmpty(), "time" to plan.anchorTime.orEmpty(), "enabled" to plan.enabled.toString()), state.value.plan != null && state.value.plan != plan)
                mutable.update { it.copy(plan = plan) }
            }
        }
        load {
            val branding = api().branding()
            if (generation == current) {
                remoteDrafts("caption_template", mapOf("caption" to branding.captionTemplate.orEmpty()), state.value.branding != null && state.value.branding?.captionTemplate != branding.captionTemplate)
                remoteDrafts("cards", mapOf("intro_duration" to (branding.introDuration?.toString() ?: "3"), "outro_duration" to (branding.outroDuration?.toString() ?: "3")), state.value.branding != null && state.value.branding != branding)
                mutable.update { it.copy(branding = branding) }
            }
        }
        load {
            val policy = api().consent()
            if (generation == current) mutable.update { it.copy(consent = policy, consentAcknowledged = it.consentAcknowledged && it.consent?.version == policy.version && policy.acceptedAt == null) }
        }
    }
    fun reloadStep(step: String) {
        if (state.value.phase != Phase.READY || state.value.busy) return
        clean(step); launch { loadConfiguration(it) }
    }
    fun acknowledgeConsent(acknowledged: Boolean) {
        mutable.update { it.copy(consentAcknowledged = acknowledged && it.consent != null && it.consent.acceptedAt == null) }
    }
    private fun mutation(step: String, action: suspend () -> Unit) {
        if (state.value.phase != Phase.READY) return
        launch { current ->
            action()
            if (generation != current) return@launch
            clean(step)
            val setup = api().setup()
            if (generation != current) return@launch
            mutable.update { it.copy(setup = setup) }
            loadConfiguration(current)
            if (generation == current && setup.checklist.any { it.key == step && it.complete }) nextStep()
        }
    }
    fun savePlan(anchorDate: String, anchorTime: String, enabled: Boolean) {
        val valid = runCatching { LocalDate.parse(anchorDate).dayOfWeek == DayOfWeek.MONDAY && LocalTime.parse(anchorTime) != null }.getOrDefault(false)
        if (!valid) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        mutation("schedule") { api().savePlan(PlanIn(anchorDate, anchorTime, enabled)) }
    }
    fun saveCaption(text: String) {
        if (text.isBlank()) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        mutation("caption_template") { api().patchBranding(buildJsonObject { put("caption_template", text) }) }
    }
    fun acceptConsent(displayedVersion: Int) {
        val policy = state.value.consent ?: return
        if (policy.acceptedAt != null || !state.value.consentAcknowledged || policy.version != displayedVersion) return
        mutation("consent") {
            try { api().acceptConsent(displayedVersion); mutable.update { it.copy(consentAcknowledged = false) } }
            catch (e: ApiFailure) {
                if (e.status != 409) throw e
                mutable.update { it.copy(consentAcknowledged = false) }
                loadConfiguration(generation)
                mutable.update { it.copy(issue = UiIssue.POLICY_CHANGED) }
                throw PolicyChanged()
            }
        }
    }
    fun nextStep() {
        val keys = state.value.setup?.checklist?.map { it.key }.orEmpty()
        val next = keys.getOrNull(keys.indexOf(state.value.step) + 1) ?: "summary"
        saved["step"] = next; mutable.update { it.copy(step = next) }
    }
    fun finishSetup() {
        if (state.value.phase != Phase.READY) return
        launch { current ->
            val setup = api().setup()
            if (generation != current) return@launch
            mutable.update { it.copy(setup = setup) }
            if (setup.ready) { closeSetup(); navigate(Destination.DASHBOARD) }
            else mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }
        }
    }
}

private class PolicyChanged : Exception()

fun safeExternalUrl(raw: String): String? = try {
    val uri = URI(raw)
    raw.takeIf { uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null }
} catch (_: Exception) { null }
