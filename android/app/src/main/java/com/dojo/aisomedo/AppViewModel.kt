package com.dojo.aisomedo

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.*
import com.dojo.aisomedo.uploads.UploadIssue
import com.dojo.aisomedo.editor.*
import com.dojo.aisomedo.reviews.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.OkHttpClient
import java.net.URI
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalTime
import java.time.Instant
import java.io.File
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
    val pendingAssets: Map<String, BrandingAssetOut> = emptyMap(),
    val editor: MediaEditorState = MediaEditorState(),
    val review: ReviewState = ReviewState(),
)

class AppViewModel(
    private val store: SessionStore,
    private val http: OkHttpClient,
    private val versionCode: Int,
    private val allowHttp: Boolean,
    val saved: SavedStateHandle,
    private val onSessionStopped: () -> Unit = {},
) : ViewModel() {
    private val mutable = MutableStateFlow(AppUiState())
    val state = mutable.asStateFlow()
    private var token: String? = null
    private var bindingId: String? = null
    private var generation = 0
    private var job: Job? = null
    private var prompted = false
    private var reviewJob: Job? = null
    private var reviewEpoch = 0

    init {
        mutable.update { it.copy(
            drafts = saved.keys().filter { key -> key.startsWith("draft_") }.associate { key -> key.removePrefix("draft_") to saved.get<String>(key).orEmpty() },
            dirtySteps = saved.get<ArrayList<String>>("dirty_steps")?.toSet().orEmpty(),
            pendingAssets = listOf("logo_asset", "intro_asset", "outro_asset").mapNotNull { field ->
                saved.get<String>("pending_$field")?.let { asset -> field to BrandingAssetOut(asset, saved.get<String>("preview_$field").orEmpty()) }
            }.toMap(),
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
            onSessionStopped()
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
            onSessionStopped()
            mutable.update { it.copy(phase = Phase.UPDATE_REQUIRED) }; return
        }
        val credential = try { withContext(Dispatchers.IO) { store.readSession(origin) } }
        catch (_: CredentialUnavailable) {
            withContext(Dispatchers.IO) { store.clearToken() }
            mutable.update { it.copy(issue = UiIssue.STORAGE) }; null
        }
        if (generation != current) return
        if (bindingId != null && bindingId != credential?.bindingId) {
            onSessionStopped()
            reviewEpoch++; reviewJob?.cancel(); clearReviewSaved()
            mutable.update { it.copy(review = ReviewState()) }
        }
        token = credential?.token
        bindingId = credential?.bindingId
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
            bindingId = withContext(Dispatchers.IO) { store.readSession(state.value.origin)?.bindingId }
            // A 401 after validation is revocation, not a rejected pairing code.
            try { authenticated(current) }
            catch (e: ApiFailure) { failure(e, false) }
        }
    }

    private suspend fun authenticated(current: Int) {
        checkSession(current)
        val client = api().me()
        if (client.kind != "device" || client.revokedAt != null) throw ApiFailure(401)
        if (generation != current) return
        mutable.update { it.copy(client = client) }
        val setup = api().setup()
        checkSession(current)
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
        checkKnownAttempt(current)
        if (state.value.destination == Destination.PACKAGE) loadEditor(current)
        restoreReviewTarget()
        if (state.value.review.target != null) refreshReview()
    }

    private fun failure(error: Exception, pairing: Boolean = false) {
        if (error is PolicyChanged) return
        if (error is ApiFailure && error.status in setOf(401, 426) && !pairing) {
            val current = runCatching { store.readSession(state.value.origin) }.getOrNull()
            if (current != null && bindingId != null && current.bindingId != bindingId) return
        }
        when {
            error is ApiFailure && error.status == 426 -> {
                onSessionStopped()
                cancelWork()
                mutable.update { it.copy(phase = Phase.UPDATE_REQUIRED, busy = false, review = ReviewState(), updateUrl = safeExternalUrl(error.updateUrl.orEmpty()) ?: it.updateUrl) }
            }
            error is ApiFailure && error.status == 401 && !pairing -> {
                onSessionStopped()
                cancelWork(); token = null; prompted = false; clearSaved()
                val issue = try { bindingId?.let { store.clearTokenIfBinding(state.value.origin, it) }; null } catch (_: Exception) { UiIssue.STORAGE }
                bindingId = null
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
        onSessionStopped()
        cancelWork(); token = null; prompted = false; clearSaved()
        bindingId = null
        val issue = try { store.setOrigin(""); null } catch (_: Exception) { UiIssue.STORAGE }
        mutable.value = AppUiState(issue = issue)
    }
    fun observeSessionFailure(issue: UploadIssue, expectedBinding: String? = null) {
        if (expectedBinding != null && expectedBinding != bindingId) return
        if (state.value.phase != Phase.READY && state.value.phase != Phase.LOADING) return
        when (issue) {
            UploadIssue.AUTH -> failure(ApiFailure(401))
            UploadIssue.UPDATE_REQUIRED -> failure(ApiFailure(426))
            else -> Unit
        }
    }
    private fun cancelWork() { generation++; job?.cancel(); job = null; reviewEpoch++; reviewJob?.cancel(); reviewJob = null }
    private fun checkSession(current: Int) {
        if (generation != current) throw CancellationException("Session changed")
    }
    private fun clearSaved() { saved.keys().toList().forEach { saved.remove<Any>(it) } }
    fun navigate(destination: Destination) {
        if (state.value.phase != Phase.READY) return
        saved["destination"] = destination.name
        closeSetup(); mutable.update { it.copy(destination = destination) }
        if (destination == Destination.PACKAGE) refreshEditor()
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
        saved["edited_$key"] = true
        mutable.update { it.copy(drafts = it.drafts + (key to value)) }; markDirty(step)
    }
    private fun clean(step: String) {
        mutable.update { it.copy(dirtySteps = it.dirtySteps - step, changedSteps = it.changedSteps - step) }
        saved["dirty_steps"] = ArrayList(state.value.dirtySteps)
        val keys = when (step) {
            "schedule" -> listOf("date", "time", "enabled")
            "caption_template" -> listOf("caption")
            "cards" -> listOf("intro_duration", "outro_duration")
            else -> emptyList()
        }
        keys.forEach { saved.remove<Boolean>("edited_$it") }
    }
    private fun remoteDrafts(step: String, values: Map<String, String>, changed: Boolean) {
        if (step in state.value.dirtySteps) {
            if (changed) mutable.update { it.copy(changedSteps = it.changedSteps + step) }
            val untouched = values.filterKeys { saved.get<Boolean>("edited_$it") != true }
            untouched.forEach { (key, value) -> saved["draft_$key"] = value }
            mutable.update { it.copy(drafts = it.drafts + untouched) }
        } else {
            values.forEach { (key, value) -> saved["draft_$key"] = value }
            mutable.update { it.copy(drafts = it.drafts + values) }
        }
    }
    private suspend fun loadConfiguration(current: Int) {
        suspend fun load(missingPolicy: Boolean = false, action: suspend () -> Unit) {
            checkSession(current)
            try { action() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                if (generation != current) return
                if (e is ApiFailure && (e.status == 401 || e.status == 426)) throw e
                if (missingPolicy && e is ApiFailure && e.status == 404) {
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
        load(missingPolicy = true) {
            val policy = api().consent()
            if (generation == current) mutable.update { it.copy(consent = policy, consentAcknowledged = it.consentAcknowledged && it.consent?.version == policy.version && policy.acceptedAt == null) }
        }
        load {
            val instagram = api().instagram()
            if (generation == current) mutable.update { it.copy(instagram = instagram) }
        }
    }
    fun reloadStep(step: String) {
        if (state.value.phase != Phase.READY || state.value.busy) return
        clean(step); launch { loadConfiguration(it) }
    }
    fun acknowledgeConsent(acknowledged: Boolean) {
        mutable.update { it.copy(consentAcknowledged = acknowledged && it.consent != null && it.consent.acceptedAt == null) }
    }
    private fun mutation(step: String, action: suspend (Int) -> Unit) {
        if (state.value.phase != Phase.READY) return
        val submittedDrafts = state.value.drafts
        val submittingStep = state.value.step
        launch { current ->
            action(current)
            checkSession(current)
            if (state.value.drafts == submittedDrafts) clean(step)
            val setup = api().setup()
            if (generation != current) return@launch
            mutable.update { it.copy(setup = setup) }
            loadConfiguration(current)
            if (generation == current && submittingStep == step && state.value.step == submittingStep &&
                step !in state.value.dirtySteps && setup.checklist.any { it.key == step && it.complete }) nextStep()
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
        mutation("consent") { current ->
            try {
                api().acceptConsent(displayedVersion)
                checkSession(current)
                mutable.update { it.copy(consentAcknowledged = false) }
            }
            catch (e: ApiFailure) {
                checkSession(current)
                if (e.status != 409) throw e
                mutable.update { it.copy(consentAcknowledged = false) }
                loadConfiguration(current)
                checkSession(current)
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
    fun connectInstagramToken(token: String) {
        if (token.isBlank() || token.length > 16384) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        mutation("instagram") { current ->
            val status = api().connectInstagramToken(token.trim())
            checkSession(current)
            mutable.update { it.copy(instagram = status) }
        }
    }
    fun startOAuth(openUrl: (String) -> Unit) {
        if (state.value.phase != Phase.READY) return
        launch { current ->
            val start = api().startOAuth()
            val url = safeExternalUrl(start.authUrl) ?: throw IllegalArgumentException("authorization URL")
            require(start.attemptId.isNotBlank())
            if (generation != current) return@launch
            saved["oauth_attempt"] = start.attemptId
            mutable.update { it.copy(attempt = AttemptOut(emptyList(), start.attemptId, "pending")) }
            openUrl(url)
        }
    }
    private suspend fun checkKnownAttempt(current: Int) {
        val id = saved.get<String>("oauth_attempt") ?: return
        val attempt = try { api().oauthAttempt(id) }
        catch (e: ApiFailure) { if (e.status == 404) AttemptOut(emptyList(), id, "unknown") else throw e }
        if (generation == current) mutable.update { it.copy(attempt = attempt) }
    }
    fun checkOAuth() {
        if (state.value.phase != Phase.READY) return
        launch { checkKnownAttempt(it) }
    }
    fun selectAccount(igUserId: String) {
        val attempt = state.value.attempt ?: return
        if (attempt.status != "completed" || attempt.candidates.none { it.igUserId == igUserId }) return
        mutation("instagram") { current ->
            val status = api().selectAccount(attempt.id, igUserId)
            checkSession(current)
            saved.remove<String>("oauth_attempt")
            mutable.update { it.copy(instagram = status, attempt = AttemptOut(emptyList(), attempt.id, "selected")) }
        }
    }
    fun uploadAsset(field: String, bytes: ByteArray) {
        require(field in listOf("logo_asset", "intro_asset", "outro_asset"))
        if (state.value.phase != Phase.READY || state.value.busy) return
        if (bytes.isEmpty() || bytes.size > 10 * 1024 * 1024 || (field != "logo_asset" && cardDuration(field) == null)) {
            mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return
        }
        mutation(if (field == "logo_asset") "logo" else "cards") { current ->
            val uploaded = api().uploadBranding(bytes)
            checkSession(current)
            saved["pending_$field"] = uploaded.asset; saved["preview_$field"] = uploaded.previewUrl
            mutable.update { it.copy(pendingAssets = it.pendingAssets + (field to uploaded)) }
            installAsset(field, uploaded, current)
        }
    }
    private fun cardDuration(field: String): Double? = state.value.drafts[field.replace("_asset", "_duration")]?.toDoubleOrNull()?.takeIf { it.isFinite() && it > 0 }
    private suspend fun installAsset(field: String, uploaded: BrandingAssetOut, current: Int) {
        checkSession(current)
        val changes = buildJsonObject {
            put(field, uploaded.asset)
            if (field != "logo_asset") put(field.replace("_asset", "_duration"), cardDuration(field) ?: throw IllegalArgumentException("duration"))
        }
        val branding = api().patchBranding(changes)
        checkSession(current)
        saved.remove<String>("pending_$field"); saved.remove<String>("preview_$field")
        mutable.update { it.copy(branding = branding, pendingAssets = it.pendingAssets - field) }
    }
    fun retryAsset(field: String) {
        val uploaded = state.value.pendingAssets[field] ?: return
        mutation(if (field == "logo_asset") "logo" else "cards") { installAsset(field, uploaded, it) }
    }
    fun saveCards(introAsset: String?, introDuration: Double?, outroAsset: String?, outroDuration: Double?) {
        fun valid(asset: String?, duration: Double?) = if (asset == null) duration == null else duration != null && duration.isFinite() && duration > 0
        if (!valid(introAsset, introDuration) || !valid(outroAsset, outroDuration)) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        val baseline = state.value.branding ?: return
        val changes = buildJsonObject {
            fun card(prefix: String, asset: String?, duration: Double?, oldAsset: String?, oldDuration: Double?) {
                if (asset != oldAsset) {
                    put("${prefix}_asset", asset?.let(::JsonPrimitive) ?: JsonNull)
                    put("${prefix}_duration", duration?.let(::JsonPrimitive) ?: JsonNull)
                } else if (duration != oldDuration) {
                    put("${prefix}_duration", duration?.let(::JsonPrimitive) ?: JsonNull)
                }
            }
            card("intro", introAsset, introDuration, baseline.introAsset, baseline.introDuration)
            card("outro", outroAsset, outroDuration, baseline.outroAsset, baseline.outroDuration)
        }
        if (changes.isNotEmpty()) mutation("cards") { api().patchBranding(changes) }
    }
    fun skipCards() { mutation("cards") { api().skipCards() } }
    suspend fun preview(path: String): ByteArray {
        require(state.value.phase == Phase.READY)
        val current = generation
        val bytes = try { api().preview(path) }
        catch (e: ApiFailure) {
            if (generation == current && (e.status == 401 || e.status == 426)) failure(e)
            throw e
        }
        if (generation != current) throw CancellationException("Session changed")
        return bytes
    }
    fun refreshEditor() {
        if (state.value.phase == Phase.READY) launch { loadEditor(it, explicit = true) }
    }
    private suspend fun loadEditor(current: Int, explicit: Boolean = false, expected: ActiveEditorOut? = null, savedTrims: Boolean = false) {
        try {
            val snapshot = api().mediaEditor()
            checkSession(current)
            mutable.update { it.copy(editor = it.editor.accept(snapshot, explicit, expected, savedTrims)) }
        } catch (e: ApiFailure) {
            checkSession(current)
            if (e.status != 404) {
                mutable.update { it.copy(editor = it.editor.copy(readRequired = true, issue = EditorIssue.READ)) }
                throw e
            }
            mutable.update { it.copy(editor = if (it.editor.dirty) it.editor.copy(snapshot = null, readRequired = true, issue = EditorIssue.CONFLICT) else MediaEditorState()) }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            checkSession(current)
            mutable.update { it.copy(editor = it.editor.copy(readRequired = true, issue = EditorIssue.READ)) }
            throw e
        }
    }
    fun editRanges(id: String, ranges: List<RangeInput>) {
        if (state.value.phase != Phase.READY || state.value.busy || state.value.editor.readRequired) return
        if (state.value.editor.snapshot?.media?.none { it.mediaId == id && it.isVideo && it.status == "finalized" } != false) return
        mutable.update { it.copy(editor = it.editor.edit(id, ranges)) }
    }
    fun discardMediaTrims() { if (!state.value.busy) mutable.update { it.copy(editor = it.editor.discard()) } }
    private fun mediaMutation(expected: ActiveEditorOut, savedTrims: Boolean = false, action: suspend (DojoApi, String) -> Unit) {
        val editor = state.value.editor
        if (state.value.phase != Phase.READY || state.value.busy || editor.readRequired || editor.snapshot == null || editor.snapshot.`package`.status == "completed") return
        val folder = editor.snapshot.`package`.folderName
        launch { current ->
            try {
                action(api(), folder)
                checkSession(current)
                // A lost read must not let the next write reuse an unverified snapshot.
                mutable.update { it.copy(editor = it.editor.copy(readRequired = true)) }
                loadEditor(current, explicit = true, expected = expected, savedTrims = savedTrims)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                checkSession(current)
                if (e is ApiFailure && e.status in setOf(401, 426)) throw e
                val issue = when ((e as? ApiFailure)?.status) {
                    422 -> EditorIssue.INVALID
                    409 -> EditorIssue.CONFLICT
                    404 -> EditorIssue.CONFLICT
                    else -> EditorIssue.UNCERTAIN
                }
                mutable.update { it.copy(editor = it.editor.copy(readRequired = issue != EditorIssue.INVALID, issue = issue)) }
            }
        }
    }
    fun reorderMedia(order: List<String>) {
        val snapshot = state.value.editor.snapshot ?: return
        if (order == snapshot.montage.order || order.size != order.toSet().size || order.toSet() != snapshot.montage.order.toSet()) return
        mediaMutation(snapshot.copy(montage = snapshot.montage.copy(order = order))) { api, folder -> api.orderMedia(folder, order) }
    }
    fun removeMedia(id: String) {
        val snapshot = state.value.editor.snapshot ?: return
        if (snapshot.media.none { it.mediaId == id && it.status == "finalized" }) return
        val expected = snapshot.copy(media = snapshot.media.map { if (it.mediaId == id) it.copy(status = "removed") else it },
            montage = snapshot.montage.copy(order = snapshot.montage.order.filter { it != id }))
        mediaMutation(expected) { api, folder -> api.removeMedia(folder, id) }
    }
    fun restoreMedia(id: String) {
        val snapshot = state.value.editor.snapshot ?: return
        val media = snapshot.media.find { it.mediaId == id && it.status == "removed" } ?: return
        val order = snapshot.montage.order.toMutableList().apply { add((media.removedPosition ?: size).coerceIn(0, size), id) }
        val expected = snapshot.copy(media = snapshot.media.map { if (it.mediaId == id) it.copy(status = "finalized") else it }, montage = snapshot.montage.copy(order = order))
        mediaMutation(expected) { api, folder -> api.restoreMedia(folder, id) }
    }
    fun saveMediaTrims() {
        val editor = state.value.editor
        if (!editor.canSave) return
        val snapshot = editor.snapshot ?: return
        val selections = editor.selections ?: return
        val removedSelections = snapshot.montage.selections.filterKeys { id -> snapshot.media.any { it.mediaId == id && it.status == "removed" } }
        mediaMutation(snapshot.copy(montage = snapshot.montage.copy(selections = removedSelections + selections)), savedTrims = true) { api, folder -> api.selectVideoRanges(folder, selections) }
    }
    fun pickerFailed() { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) } }

    private fun saveReviewTarget(target: ReviewTarget) {
        saved["review_id"] = target.reviewId
        saved["review_occurrence"] = target.occurrenceId
        saved["review_folder"] = target.packageFolder
        saved["review_version"] = target.expectedVersion
        saved["review_action"] = target.action.name
        saved["review_origin"] = state.value.origin
        saved["review_binding"] = bindingId
    }
    private fun restoreReviewTarget() {
        if (state.value.review.target != null || saved.get<String>("review_origin") == null) return
        if (saved.get<String>("review_origin") != state.value.origin || saved.get<String>("review_binding") != bindingId) {
            clearReviewSaved(); return
        }
        val target = runCatching { ReviewTarget(saved["review_id"], saved["review_occurrence"], saved["review_folder"], saved["review_version"],
            ReviewAction.valueOf(saved.get<String>("review_action") ?: "REVIEW")) }.getOrNull()
        if (target?.valid != true) { clearReviewSaved(); return }
        mutable.update { it.copy(review = ReviewState(target = target)) }
    }
    private fun clearReviewSaved() { saved.keys().filter { it.startsWith("review_") }.forEach { saved.remove<Any>(it) } }
    fun openReview(target: ReviewTarget) {
        if (state.value.phase != Phase.READY || !target.valid) return
        reviewEpoch++; reviewJob?.cancel()
        saved["review_owner"] = state.value.destination.name
        saveReviewTarget(target)
        mutable.update { it.copy(review = ReviewState(target = target)) }
        refreshReview()
    }
    fun closeReview() {
        reviewEpoch++; reviewJob?.cancel(); reviewJob = null
        val owner = Destination.entries.firstOrNull { it.name == saved.get<String>("review_owner") } ?: state.value.destination
        clearReviewSaved(); saved["destination"] = owner.name
        mutable.update { it.copy(review = ReviewState(), destination = owner) }
    }
    private fun checkReview(current: Int, epoch: Int) {
        checkSession(current)
        if (epoch != reviewEpoch || state.value.phase != Phase.READY) throw CancellationException("Review changed")
        if (runCatching { store.readSession(state.value.origin)?.bindingId }.getOrNull() != bindingId) {
            clearReviewSaved()
            mutable.update { it.copy(review = ReviewState()) }
            throw CancellationException("Session binding changed")
        }
    }
    private fun reviewWork(mutation: Boolean = false, action: suspend (Int, Int) -> Unit) {
        if (state.value.phase != Phase.READY || state.value.review.busy || state.value.review.target == null || mutation && state.value.busy) return
        val current = generation
        val epoch = reviewEpoch
        mutable.update { it.copy(review = it.review.copy(busy = true)) }
        reviewJob = viewModelScope.launch {
            try { checkReview(current, epoch); action(current, epoch) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                checkReview(current, epoch)
                if (e is ApiFailure && e.status in setOf(401, 426)) failure(e)
                else mutable.update { it.copy(review = it.review.copy(readRequired = true, issue = when {
                    mutation -> ReviewIssue.UNCERTAIN
                    e is ApiFailure && e.status == 404 -> ReviewIssue.NOT_FOUND
                    e is ApiFailure -> ReviewIssue.NETWORK
                    else -> ReviewIssue.INVALID_RESPONSE
                })) }
            } finally {
                if (generation == current && reviewEpoch == epoch) mutable.update { it.copy(review = it.review.copy(busy = false)) }
            }
        }
    }
    fun refreshReview() { reviewWork { current, epoch -> loadReview(current, epoch) } }
    fun pollReview() {
        val review = state.value.review
        if (review.target != null && !review.busy && review.issue == null &&
            (review.detail?.review?.status == "pending" || review.target.occurrenceId != null)) refreshReview()
    }
    suspend fun downloadReviewPreview(id: Int, revision: String, destination: File) {
        val current = generation
        val epoch = reviewEpoch
        fun requirePreview(): String {
            checkReview(current, epoch)
            val review = state.value.review
            val detail = requireNotNull(review.detail)
            require(review.target?.reviewId == id && detail.review.id == id &&
                detail.review.revisionDigest == revision && detail.renderReady && review.issue == null)
            return requireNotNull(detail.previewUrl)
        }
        try {
            api().downloadReviewPreview(requirePreview(), destination)
            requirePreview()
        } catch (e: CancellationException) { destination.delete(); throw e }
        catch (e: Exception) {
            destination.delete()
            if (generation == current && reviewEpoch == epoch && e is ApiFailure && e.status in setOf(401, 426)) failure(e)
            throw e
        }
    }
    private suspend fun loadReview(current: Int, epoch: Int) {
        val target = state.value.review.target ?: return
        val transport = api()
        if (target.reviewId != null) {
            val detail = transport.review(target.reviewId)
            checkReview(current, epoch)
            require(detail.review.id > 0 && detail.review.version > 0 && detail.review.revisionDigest.isNotBlank() &&
                detail.review.packageFolder.isNotBlank() && detail.review.status in setOf("pending", "approved", "skipped", "rescheduled"))
            val issue = when {
                detail.review.id != target.reviewId || target.packageFolder != null && target.packageFolder != detail.review.packageFolder -> ReviewIssue.STALE
                detail.review.status != "pending" -> ReviewIssue.ALREADY_HANDLED
                target.expectedVersion != null && target.expectedVersion != detail.review.version -> ReviewIssue.STALE
                else -> null
            }
            val bound = target.copy(packageFolder = target.packageFolder ?: detail.review.packageFolder,
                expectedVersion = target.expectedVersion ?: detail.review.version)
            saveReviewTarget(bound)
            mutable.update { state ->
                val previous = state.review.detail
                state.copy(review = state.review.copy(target = bound, detail = detail, readRequired = issue != null,
                    issue = issue, nextRegularAt = detail.nextRegularAt,
                    previewReady = state.review.previewReady && issue == null && detail.renderReady &&
                        previous?.review?.id == detail.review.id && previous.review.revisionDigest == detail.review.revisionDigest &&
                        previous.review.version == detail.review.version))
            }
        } else {
            val dashboard = transport.dashboard()
            checkReview(current, epoch)
            val pending = dashboard.pendingActions.find { it.occurrenceId == target.occurrenceId }
            val issue = when {
                pending == null -> ReviewIssue.ALREADY_HANDLED
                pending.packageFolder != target.packageFolder || dashboard.`package`?.folderName != target.packageFolder -> ReviewIssue.PACKAGE_CHANGED
                pending.reviewId != null || pending.state != "empty_package" -> ReviewIssue.STALE
                else -> null
            }
            mutable.update { it.copy(dashboard = dashboard, review = it.review.copy(readRequired = issue != null,
                issue = issue, nextRegularAt = dashboard.nextSlot?.takeIf { slot -> slot.kind == "regular" }?.dueAt)) }
        }
    }
    fun requestReviewAction(action: ReviewAction) {
        val review = state.value.review
        val target = review.target ?: return
        if (state.value.phase != Phase.READY || review.busy) return
        val updated = target.copy(action = action)
        saveReviewTarget(updated)
        mutable.update { it.copy(review = it.review.copy(target = updated)) }
    }
    fun markReviewPreviewReady(id: Int, revision: String, ready: Boolean) {
        val review = state.value.review
        val detail = review.detail ?: return
        if (state.value.phase != Phase.READY || review.target?.reviewId != id || detail.review.id != id ||
            detail.review.revisionDigest != revision || ready && (!detail.renderReady || review.issue != null)) return
        mutable.update { it.copy(review = it.review.copy(previewReady = ready)) }
    }
    fun approveReview() {
        if (state.value.review.canApprove) decideReview("approve")
    }
    fun skipReview() {
        if (state.value.review.canDecide && state.value.review.target?.action == ReviewAction.SKIP) decideReview("skip")
    }
    fun rescheduleReview(date: LocalDate, time: LocalTime) {
        val review = state.value.review
        val validated = review.copy(issue = review.issue.takeUnless { it == ReviewIssue.INVALID_TIME })
        if (!validated.canDecide || review.target?.action != ReviewAction.RESCHEDULE) return
        val due = futureIstanbulInstant(date, time, Instant.now())
        if (due == null) { mutable.update { it.copy(review = it.review.copy(issue = ReviewIssue.INVALID_TIME)) }; return }
        mutable.update { it.copy(review = it.review.copy(issue = null)) }
        decideReview("reschedule", due)
    }
    private fun decideReview(action: String, due: String? = null) {
        val target = state.value.review.target ?: return
        val detail = state.value.review.detail
        reviewWork(mutation = true) { current, epoch ->
            val transport = api()
            try {
                val result = if (target.reviewId != null && detail != null) {
                    when (action) {
                        "approve" -> transport.approveReview(target.reviewId, detail.review.version)
                        "skip" -> transport.skipReview(target.reviewId, detail.review.version)
                        else -> transport.rescheduleReview(target.reviewId, detail.review.version, requireNotNull(due))
                    }
                } else {
                    val id = requireNotNull(target.occurrenceId)
                    val folder = requireNotNull(target.packageFolder)
                    val decision = if (action == "skip") transport.skipEmptyOccurrence(id, EmptySkipIn(expectedFolderName = folder, confirmed = true))
                        else transport.rescheduleEmptyOccurrence(id, EmptyRescheduleIn(folder, requireNotNull(due)))
                    checkReview(current, epoch)
                    require(decision.occurrenceId == id && decision.packageFolder == folder)
                    mutable.update { it.copy(review = it.review.copy(nextRegularAt = decision.nextRegularAt, continuing = false)) }
                    null
                }
                checkReview(current, epoch)
                mutable.update { it.copy(review = it.review.copy(readRequired = true, publication = result?.get("publication") as? JsonObject)) }
                loadReview(current, epoch)
                val dashboard = transport.dashboard()
                checkReview(current, epoch)
                mutable.update { it.copy(dashboard = dashboard) }
            } catch (e: ApiFailure) {
                checkReview(current, epoch)
                if (e.status == 409) {
                    loadReview(current, epoch)
                    mutable.update { it.copy(review = it.review.copy(readRequired = true,
                        issue = if (it.review.detail?.review?.status?.let { status -> status != "pending" } == true)
                            ReviewIssue.ALREADY_HANDLED else ReviewIssue.STALE)) }
                } else throw e
            }
        }
    }
}

private class PolicyChanged : Exception()

fun safeExternalUrl(raw: String): String? = try {
    val uri = URI(raw)
    raw.takeIf { uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null }
} catch (_: Exception) { null }
