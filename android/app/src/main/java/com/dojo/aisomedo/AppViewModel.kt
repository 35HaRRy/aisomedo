package com.dojo.aisomedo

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.*
import com.dojo.aisomedo.uploads.UploadIssue
import com.dojo.aisomedo.uploads.UploadRecord
import com.dojo.aisomedo.uploads.UploadPhase
import com.dojo.aisomedo.editor.*
import com.dojo.aisomedo.reviews.*
import com.dojo.aisomedo.notifications.*
import com.dojo.aisomedo.offline.*
import com.dojo.aisomedo.live.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.OkHttpClient
import java.net.URI
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.Instant
import java.io.File
import kotlinx.serialization.json.*

enum class Phase { ADDRESS, LOADING, PAIRING, READY, UPDATE_REQUIRED, CONNECTION_ERROR }
enum class Destination { DASHBOARD, PACKAGE, COMPLETED, ACTIVITY, SETTINGS }
enum class UiIssue { INVALID_SERVER, NETWORK, INVALID_CODE, RATE_LIMIT, INVALID_INPUT, PROVIDER_UNAVAILABLE, POLICY_MISSING, POLICY_CHANGED, STORAGE, UNKNOWN }

data class AppUiState(
    val phase: Phase = Phase.ADDRESS,
    val origin: String = "",
    val client: ClientOut? = null,
    val compat: CompatInfo? = null,
    val dashboard: DashboardOut? = null,
    val dashboardRevision: Long = 0,
    val setup: SetupOut? = null,
    val destination: Destination = Destination.DASHBOARD,
    val step: String? = null,
    val busy: Boolean = false,
    val stale: Boolean = false,
    val issue: UiIssue? = null,
    val updateUrl: String? = null,
    val plan: PlanOut? = null,
    val reminders: ReminderPolicyOut? = null,
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
    val oneoffDecision: OneoffDecisionOut? = null,
    val oneoffDecisionIssue: ReviewIssue? = null,
    val outcomePackage: String? = null,
    val networkConnected: Boolean = true,
    val authoritative: Boolean = false,
    val configurationFresh: Set<String> = emptySet(),
    val activity: ActivityPageOut? = null,
    val dashboardFetchedAt: Long? = null,
    val editorFetchedAt: Long? = null,
    val activityFetchedAt: Long? = null,
    val livePhase: LivePhase = LivePhase.CONNECTING,
    val completedPackages: List<PackageOut>? = null,
    val completedFolder: String? = null,
    val completedDetail: CompletedPackageOut? = null,
    val completedError: Boolean = false,
    val pendingClearFolder: String? = null,
    val clearReadRequired: Boolean = false,
) {
    val showConnectionNotice get() = phase == Phase.READY &&
        (!networkConnected || livePhase == LivePhase.DISCONNECTED || !authoritative && issue != null)
    val canMutate get() = phase == Phase.READY && livePhase == LivePhase.LIVE && networkConnected && authoritative && !busy
    val canEditMedia get() = canMutate && !editor.readRequired && editor.snapshot != null &&
        editor.snapshot.`package` == dashboard?.`package` && editor.snapshot.`package`.status != "completed"
    fun canConfigure(step: String) = canMutate && step in configurationFresh
}

class AppViewModel(
    private val store: SessionStore,
    private val http: OkHttpClient,
    private val versionCode: Int,
    private val allowHttp: Boolean,
    val saved: SavedStateHandle,
    private val snapshots: SnapshotStore? = null,
    private val network: StateFlow<NetworkStatus> = MutableStateFlow(NetworkStatus(true)),
    private val now: () -> Long = System::currentTimeMillis,
    private val draftStore: DraftStore? = null,
    private val onSessionStopped: () -> Unit = {},
) : ViewModel() {
    private val initialNetwork = network.value
    private val mutable = MutableStateFlow(AppUiState(networkConnected = initialNetwork.connected))
    val state = mutable.asStateFlow()
    private var token: String? = null
    private var bindingId: String? = null
    val currentBinding get() = bindingId
    val writesAllowed get() = admit()
    private var generation = 0
    private var job: Job? = null
    private var prompted = false
    private var reviewJob: Job? = null
    private var reviewEpoch = 0
    private var oneoffEpoch = 0
    private var oneoffDecisionRevision = 0L
    private var pendingPushRefresh = false
    private var refreshRequested = false
    private var boundRevision = store.revision.value
    private var authoritativeEpoch: Long? = null
    private var writingSession = false
    private var foreground = false
    private var live: LiveCoordinator? = null
    private var liveBinding: String? = null
    private var liveObservation: Job? = null
    private var liveReading = false
    private val snapshotVersions = SnapshotVersions()
    private var draftOwner: Pair<String, String>? = null
    private var draftSequence = 0L
    private var draftWrite: Deferred<Boolean>? = null
    private var cleared = false

    private fun persistEditor(editor: MediaEditorState, packageId: Int? = editor.draftPackageId ?: editor.snapshot?.`package`?.id): Deferred<Boolean> {
        val origin = state.value.origin; val binding = bindingId; val current = generation
        val sequence = ++draftSequence; val previous = draftWrite
        val draft = editor.storedDraft?.copy(localRevision = sequence)
        mutable.update { it.copy(editor = editor.copy(storedDraft = draft, persisting = true)) }
        // Finish already accepted writes even when the screen closes. Never update a replacement session.
        val work = viewModelScope.async(NonCancellable) {
            previous?.await()
            var issue: DraftIssue? = null
            val success = try {
                check(binding != null && packageId != null && draftStore != null)
                withContext(Dispatchers.IO) { synchronized(store) {
                    if (store.readSession(origin)?.bindingId != binding) return@synchronized false
                    if (draft == null) draftStore.clear(origin, binding, packageId)
                    else draftStore.write(origin, binding, packageId, draft)
                    true
                } }
            } catch (error: Exception) { issue = (error as? DraftFailure)?.issue ?: DraftIssue.STORAGE; false }
            if (!cleared && generation == current && sequence == draftSequence) mutable.update {
                it.copy(editor = it.editor.copy(persisting = false, persistenceIssue = issue))
            }
            success
        }
        draftWrite = work
        return work
    }

    private suspend fun restoreEditorDraft(current: Int, packageId: Int?) {
        val binding = bindingId ?: return
        val identity = state.value.origin to binding
        if (draftOwner == identity || draftStore == null) return
        draftOwner = identity
        draftWrite?.await()
        try {
            val rows = withContext(Dispatchers.IO) { draftStore.list(identity.first, binding) }
            checkSession(current)
            val selected = rows[packageId]?.let { packageId!! to it } ?: rows.maxByOrNull { it.key }?.toPair() ?: return
            draftSequence = maxOf(draftSequence, selected.second.localRevision)
            mutable.update { it.copy(editor = it.editor.restore(selected.first, selected.second)) }
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) {
            if (generation == current) mutable.update { it.copy(editor = it.editor.copy(
                persistenceIssue = (error as? DraftFailure)?.issue ?: DraftIssue.STORAGE, readRequired = true)) }
        }
    }

    fun retryEditorPersistence() {
        if (!admit() || state.value.editor.persistenceIssue != DraftIssue.STORAGE) return
        persistEditor(state.value.editor.copy(persistenceIssue = null))
    }

    fun resolveMediaConflict(key: String, local: Boolean) {
        if (!admit() || state.value.editor.persistenceIssue != null) return
        persistEditor(state.value.editor.resolveConflict(key, local))
    }

    fun setForeground(active: Boolean) {
        foreground = active
        live?.setForeground(active && network.value.connected)
        mutable.update { it.copy(livePhase = live?.phase?.value ?: LivePhase.CONNECTING) }
    }

    private fun startLive() {
        if (live != null && liveBinding == bindingId) return
        stopLive()
        liveBinding = bindingId
        val coordinator = LiveCoordinator(viewModelScope, { api().liveEvents() }, ::refreshLive,
            { failure(it) }, snapshotVersions::observe)
        live = coordinator
        liveObservation = viewModelScope.launch {
            coordinator.phase.collect { phase -> mutable.update { it.copy(livePhase = phase) } }
        }
        coordinator.setForeground(foreground && network.value.connected)
    }

    private fun stopLive() {
        liveObservation?.cancel(); liveObservation = null
        live?.stop(); live = null; liveBinding = null
        snapshotVersions.reset()
        liveReading = false
        mutable.update { it.copy(livePhase = LivePhase.DISCONNECTED) }
    }

    private suspend fun refreshLive(resources: Set<String>) {
        state.first { !it.busy && !it.review.busy }
        val current = generation; val epoch = network.value.epoch
        checkRead(current, epoch)
        val all = "*" in resources
        val content = all || resources.any { it.startsWith("package:") } || "publication" in resources
        // ponytail: serialize live snapshot batches; split by resource only if foreground reads become slow.
        liveReading = true
        mutable.update { it.copy(busy = true) }
        try {
            if (all || "setup" in resources || "settings" in resources) {
                val setup = api().setup(); checkRead(current, epoch)
                mutable.update { it.copy(setup = setup) }
                if (state.value.step != null || state.value.destination == Destination.SETTINGS) {
                    loadConfiguration(current)
                    val required = setOf("schedule", "logo", "cards", "caption_template", "instagram") +
                        if (state.value.destination == Destination.SETTINGS) setOf("reminders") else emptySet()
                    check(state.value.configurationFresh.containsAll(required))
                }
            }
            if (content || "dashboard" in resources) {
                val dashboard = api().dashboard(); checkRead(current, epoch)
                mutable.update { it.copy(dashboard = dashboard, dashboardRevision = it.dashboardRevision + 1,
                    dashboardFetchedAt = now(), stale = false) }
            }
            if (content && (state.value.dashboard?.`package` != null || state.value.editor.snapshot != null || state.value.destination == Destination.PACKAGE)) loadEditor(current, explicit = !state.value.editor.dirty)
            if ((all || "activity" in resources) && state.value.destination == Destination.ACTIVITY) {
                val activity = api().activity(); checkRead(current, epoch)
                require(activity.events.size <= 50)
                mutable.update { it.copy(activity = activity, activityFetchedAt = now()) }
            }
            if ((all || "completed" in resources) && state.value.destination == Destination.COMPLETED) loadCompleted(current)
            if (state.value.review.target != null && state.value.review.issue != ReviewIssue.UNCERTAIN && (content || "dashboard" in resources)) loadReview(current, reviewEpoch)
            checkRead(current, epoch)
            authoritativeEpoch = epoch
            mutable.update { it.copy(authoritative = true) }
            persistState(current)
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) {
            if (generation == current) { mutable.update { it.copy(authoritative = false) }; failure(error) }
            throw error
        } finally { if (generation == current) { liveReading = false; mutable.update { it.copy(busy = false) }; resumeOneoffReview() } }
    }

    override fun onCleared() { cleared = true; stopLive(); super.onCleared() }

    init {
        mutable.update { it.copy(
            pendingClearFolder = saved.get<String>("clear_package_folder"),
            clearReadRequired = saved.get<Boolean>("clear_requires_read") ?: saved.contains("clear_package_id"),
            drafts = saved.keys().filter { key -> key.startsWith("draft_") }.associate { key -> key.removePrefix("draft_") to saved.get<String>(key).orEmpty() },
            dirtySteps = saved.get<ArrayList<String>>("dirty_steps")?.toSet().orEmpty(),
            pendingAssets = listOf("logo_asset", "intro_asset", "outro_asset").mapNotNull { field ->
                saved.get<String>("pending_$field")?.let { asset -> field to BrandingAssetOut(asset, saved.get<String>("preview_$field").orEmpty()) }
            }.toMap(),
        ) }
        try { mutable.update { it.copy(origin = store.origin.orEmpty()) } }
        catch (_: Exception) { mutable.update { it.copy(issue = UiIssue.STORAGE) } }
        viewModelScope.launch {
            store.revision.collect { revision ->
                if (!writingSession && bindingId != null && revision != boundRevision) invalidateSession()
            }
        }
        viewModelScope.launch {
            var observed = initialNetwork
            network.collect { status ->
                if (status == observed) return@collect
                observed = status
                live?.setForeground(foreground && status.connected)
                authoritativeEpoch = null
                mutable.update { it.copy(networkConnected = status.connected, authoritative = false, configurationFresh = emptySet(),
                    stale = it.client != null, editor = it.editor.copy(readRequired = true),
                    review = it.review.copy(readRequired = true, previewReady = false)) }
                if (status.connected) refreshRequested = true
                if (status.connected && !state.value.busy) { refreshRequested = false; refresh() }
            }
        }
        refresh()
    }

    private fun api() = DojoApi(state.value.origin, token, versionCode, http, versions = snapshotVersions)
    private fun launch(pairing: Boolean = false, action: suspend (Int) -> Unit) {
        if (state.value.busy) return
        val current = generation
        mutable.update { it.copy(busy = true, issue = null) }
        job = viewModelScope.launch {
            try { action(current) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (generation == current) failure(e, pairing) }
            finally { if (generation == current) {
                mutable.update { it.copy(busy = false) }
                resumeOneoffReview()
                if (pendingPushRefresh) { pendingPushRefresh = false; if (state.value.phase == Phase.READY) refresh() }
                if (refreshRequested) { refreshRequested = false; refresh() }
            } }
        }
    }

    fun submitOrigin(raw: String) {
        if (state.value.busy) return
        val origin = try { ApiConfig.normalizeOrigin(raw, allowHttp) }
        catch (_: Exception) { mutable.update { it.copy(issue = UiIssue.INVALID_SERVER) }; return }
        launch {
            onSessionStopped()
            writingSession = true
            try {
                withContext(Dispatchers.IO) { synchronized(store) { store.setOrigin(origin); snapshots?.clear() } }
                token = null; bindingId = null; boundRevision = store.revision.value
            } finally { writingSession = false }
            mutable.value = AppUiState(origin = origin, busy = true, networkConnected = network.value.connected)
            boot(it)
        }
    }

    fun refresh() {
        if (state.value.origin.isBlank()) return
        launch { current -> boot(current) }
        if (live?.phase?.value == LivePhase.SYNCING) live?.invalidate(setOf("*"))
    }

    private suspend fun boot(current: Int) {
        var storageIssue = false
        writingSession = true
        val read = try { withContext(Dispatchers.IO) { synchronized(store) {
            val origin = store.origin.orEmpty()
            val before = store.revision.value
            val credential = try { if (origin.isBlank()) null else store.readSession(origin) }
            catch (_: CredentialUnavailable) {
                if (generation != current || before != store.revision.value || store.origin != origin) return@synchronized null
                store.clearToken()
                runCatching { snapshots?.update(origin) { it.copy(data = null) } }
                storageIssue = true
                null
            }
            if (generation != current || (credential != null && before != store.revision.value)) return@synchronized null
            val cached = if (origin.isBlank()) null else snapshots?.read(origin, credential?.bindingId)
            Triple(origin, credential, store.revision.value) to cached
        } } } finally { writingSession = false }
        if (generation != current) return
        if (read == null || read.first.third != store.revision.value) { invalidateSession(); return }
        val (identity, cached) = read
        val (configuredOrigin, credential, revision) = identity
        if (configuredOrigin.isBlank()) {
            token = null; bindingId = null; boundRevision = revision
            mutable.value = AppUiState(networkConnected = network.value.connected)
            return
        }
        val origin = ApiConfig.normalizeOrigin(configuredOrigin, allowHttp)
        val changed = bindingId != credential?.bindingId || state.value.origin != origin
        if (changed && state.value.client != null) {
            clearSaved(); prompted = false; reviewEpoch++; reviewJob?.cancel()
            mutable.update { AppUiState(origin = origin, busy = it.busy, networkConnected = network.value.connected) }
        }
        token = credential?.token; bindingId = credential?.bindingId; boundRevision = revision
        if (saved.get<Int>("clear_package_id") != null &&
            (saved.get<String>("clear_origin") != origin || saved.get<String>("clear_binding") != bindingId)) forgetClearTarget()
        mutable.update { it.copy(origin = origin, issue = if (storageIssue) UiIssue.STORAGE else it.issue) }
        cached?.let { value ->
            mutable.update { it.copy(compat = value.compat ?: it.compat, updateUrl = value.updateUrl ?: it.updateUrl) }
            if (state.value.client == null) value.data?.let { data ->
                mutable.update { it.copy(phase = Phase.READY, client = data.client, setup = data.setup, dashboard = data.dashboard,
                    editor = (data.editor?.let { snapshot -> MediaEditorState().accept(snapshot) } ?: MediaEditorState()).copy(readRequired = true),
                    activity = data.activity, dashboardFetchedAt = data.dashboardFetchedAt, editorFetchedAt = data.editorFetchedAt,
                    activityFetchedAt = data.activityFetchedAt, stale = true, authoritative = false, step = null) }
                if (!network.value.connected) prompted = true
            }
        }
        restoreEditorDraft(current, cached?.data?.editor?.`package`?.id)
        if (cached?.rejectedVersionCode == versionCode || cached?.compat?.let { UpdatePolicy.isOutdated(versionCode, it.androidMinVersionCode) } == true) {
            onSessionStopped(); mutable.update { it.copy(phase = Phase.UPDATE_REQUIRED, authoritative = false) }
        }
        if (!network.value.connected) {
            mutable.update { it.copy(issue = UiIssue.NETWORK, authoritative = false,
                phase = if (it.phase in setOf(Phase.READY, Phase.UPDATE_REQUIRED)) it.phase else Phase.CONNECTION_ERROR) }
            return
        }
        val epoch = network.value.epoch
        mutable.update { it.copy(authoritative = false) }
        if (state.value.client == null && state.value.phase != Phase.UPDATE_REQUIRED) mutable.update { it.copy(phase = Phase.LOADING) }
        val compat = DojoApi(origin, null, versionCode, http).compat()
        require(compat.androidMinVersionCode >= 1 && compat.androidCurrentVersionCode >= compat.androidMinVersionCode)
        checkRead(current, epoch)
        mutable.update { it.copy(compat = compat, updateUrl = safeExternalUrl(compat.updateUrl)) }
        persist(current) { it.copy(compat = compat, updateUrl = safeExternalUrl(compat.updateUrl), rejectedVersionCode = null) }
        if (UpdatePolicy.isOutdated(versionCode, compat.androidMinVersionCode)) {
            onSessionStopped()
            mutable.update { it.copy(phase = Phase.UPDATE_REQUIRED) }; return
        }
        if (state.value.phase == Phase.UPDATE_REQUIRED) mutable.update { it.copy(phase = Phase.LOADING) }
        if (token == null) { mutable.update { it.copy(phase = Phase.PAIRING) }; return }
        authenticated(current, epoch)
    }

    fun pair(code: String, name: String) {
        if (state.value.phase != Phase.PAIRING || !network.value.connected) return
        if (code.isBlank() || name.isBlank()) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        launch(pairing = true) { current ->
            val result = api().pair(code.trim(), name.trim())
            val credential = result.token
            require(result.kind == "device" && !credential.isNullOrBlank())
            if (generation != current) return@launch
            writingSession = true
            try {
                val identity = withContext(Dispatchers.IO) { synchronized(store) {
                    if (generation != current) return@synchronized null
                    store.saveToken(state.value.origin, credential)
                    store.readSession(state.value.origin) to store.revision.value
                } } ?: return@launch
                if (generation != current) return@launch
                token = identity.first?.token; bindingId = identity.first?.bindingId; boundRevision = identity.second
            } finally { writingSession = false }
            // A 401 after validation is revocation, not a rejected pairing code.
            try { authenticated(current) }
            catch (e: ApiFailure) { failure(e, false) }
        }
    }

    private suspend fun authenticated(current: Int, epoch: Long = network.value.epoch) {
        checkSession(current)
        val client = api().me()
        if (client.kind != "device" || client.revokedAt != null) throw ApiFailure(401)
        checkRead(current, epoch)
        mutable.update { it.copy(client = client) }
        restoreEditorDraft(current, state.value.editor.snapshot?.`package`?.id)
        startLive()
        val setup = api().setup()
        checkRead(current, epoch)
        var step = state.value.step
        if (!prompted) {
            prompted = true
            step = saved.get<String>("step") ?: if (!setup.ready) setup.checklist.firstOrNull { it.required && !it.complete }?.key else null
        }
        val destination = Destination.entries.firstOrNull { it.name == saved.get<String>("destination") } ?: state.value.destination
        mutable.update { it.copy(phase = Phase.READY, client = client, setup = setup, step = step, destination = destination) }
        readSection(current) {
            val dashboard = api().dashboard()
            checkRead(current, epoch)
            authoritativeEpoch = epoch
            mutable.update {
                val changedPackage = it.editor.snapshot?.`package` != dashboard.`package`
                it.copy(dashboard = dashboard, dashboardRevision = it.dashboardRevision + 1, dashboardFetchedAt = now(), authoritative = true, stale = false,
                    editor = if (changedPackage && it.editor.storedDraft == null) MediaEditorState() else it.editor,
                    editorFetchedAt = if (changedPackage) null else it.editorFetchedAt)
            }
            persistState(current)
        }
        readSection(current) {
            val activity = api().activity()
            checkRead(current, epoch)
            require(activity.events.size <= 50)
            mutable.update { it.copy(activity = activity, activityFetchedAt = now()) }
            persistState(current)
        }
        if (step != null || state.value.destination == Destination.SETTINGS) loadConfiguration(current)
        checkKnownAttempt(current)
        if (state.value.dashboard?.`package` != null || state.value.destination == Destination.PACKAGE) readSection(current) { loadEditor(current) }
        if (state.value.destination == Destination.COMPLETED) readSection(current) { loadCompleted(current) }
        persistState(current)
        restoreReviewTarget()
        if (state.value.review.target != null) refreshReview()
        consumeNotification()
    }

    private suspend fun readSection(current: Int, action: suspend () -> Unit) {
        try { action() }
        catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            checkSession(current)
            if (e is ApiFailure && e.status in setOf(401, 426)) throw e
            failure(e)
        }
    }
    private suspend fun persist(current: Int, change: (CachedSnapshot) -> CachedSnapshot) {
        val target = snapshots ?: return
        val origin = state.value.origin; val binding = bindingId
        try { withContext(Dispatchers.IO) {
            synchronized(store) {
                if (generation == current && state.value.origin == origin && store.readSession(origin)?.bindingId == binding) target.update(origin, change)
            }
        } } catch (e: CancellationException) { throw e }
        catch (_: Exception) { if (generation == current) mutable.update { it.copy(issue = UiIssue.STORAGE) } }
    }
    private suspend fun persistState(current: Int) {
        val value = state.value
        val binding = bindingId ?: return
        val client = value.client ?: return; val setup = value.setup ?: return
        persist(current) { it.copy(data = CachedContent(binding, client, setup, value.dashboard, value.editor.snapshot,
            value.activity, value.dashboardFetchedAt, value.editorFetchedAt, value.activityFetchedAt)) }
    }
    private suspend fun failure(error: Exception, pairing: Boolean = false) {
        if (error is PolicyChanged) return
        if (error is ApiFailure && error.status in setOf(401, 426) && !pairing) {
            val observedGeneration = generation; val observedBinding = bindingId; val origin = state.value.origin
            val current = withContext(Dispatchers.IO) { runCatching { store.readSession(origin) }.getOrNull() }
            if (generation != observedGeneration || bindingId != observedBinding || state.value.origin != origin) return
            if (current != null && observedBinding != null && current.bindingId != observedBinding) { invalidateSession(); return }
        }
        when {
            error is ApiFailure && error.status == 426 -> {
                val current = generation
                persist(current) { it.copy(rejectedVersionCode = versionCode, updateUrl = safeExternalUrl(error.updateUrl.orEmpty()) ?: it.updateUrl) }
                if (generation != current) return
                onSessionStopped()
                cancelWork()
                mutable.update { it.copy(phase = Phase.UPDATE_REQUIRED, busy = false, authoritative = false, review = ReviewState(), updateUrl = safeExternalUrl(error.updateUrl.orEmpty()) ?: it.updateUrl) }
            }
            error is ApiFailure && error.status == 401 && !pairing -> {
                onSessionStopped()
                cancelWork(); token = null; prompted = false; clearSaved()
                val current = generation
                val origin = state.value.origin; val binding = bindingId
                bindingId = null
                mutable.value = AppUiState(origin = origin, compat = state.value.compat, phase = Phase.PAIRING, busy = true, networkConnected = network.value.connected)
                val issue = try { withContext(NonCancellable + Dispatchers.IO) { synchronized(store) {
                    if (generation == current && binding != null && store.clearTokenIfBinding(origin, binding)) snapshots?.update(origin) { it.copy(data = null) }
                } }; null } catch (_: Exception) { UiIssue.STORAGE }
                if (generation != current) return
                mutable.value = AppUiState(origin = origin, compat = state.value.compat, phase = Phase.PAIRING, issue = issue, networkConnected = network.value.connected)
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
                mutable.update { it.copy(issue = issue, stale = it.dashboard != null, authoritative = if (error is ApiFailure && error.status in setOf(0, 502, 503)) false else it.authoritative,
                    phase = if (it.phase == Phase.LOADING) Phase.CONNECTION_ERROR else it.phase) }
            }
        }
    }

    fun changeServer() {
        val origin = state.value.origin; val binding = bindingId
        onSessionStopped()
        cancelWork(); token = null; prompted = false; clearSaved()
        bindingId = null
        val issue = try { store.setOrigin(""); null } catch (_: Exception) { UiIssue.STORAGE }
        val current = generation
        viewModelScope.launch(NonCancellable + Dispatchers.IO) { runCatching { synchronized(store) {
            if (store.origin == null) snapshots?.clear()
            if (binding != null) draftStore?.clearIdentity(origin, binding)
        } }.onFailure { if (!cleared && current == generation) mutable.update { it.copy(issue = UiIssue.STORAGE) } } }
        mutable.value = AppUiState(issue = issue, networkConnected = network.value.connected)
    }
    fun observeSessionFailure(issue: UploadIssue, expectedBinding: String? = null) {
        if (expectedBinding != null && expectedBinding != bindingId) return
        if (state.value.phase != Phase.READY && state.value.phase != Phase.LOADING) return
        val current = generation; val binding = bindingId; val revision = boundRevision
        val status = when (issue) { UploadIssue.AUTH -> 401; UploadIssue.UPDATE_REQUIRED -> 426; else -> return }
        viewModelScope.launch {
            if (generation == current && bindingId == binding && store.revision.value == revision) failure(ApiFailure(status))
        }
    }
    private fun cancelWork() { stopLive(); generation++; job?.cancel(); job = null; reviewEpoch++; reviewJob?.cancel(); reviewJob = null; pendingPushRefresh = false; clearNotificationSaved() }
    private fun invalidateSession() {
        if (bindingId != null || state.value.client != null) onSessionStopped()
        cancelWork(); token = null; bindingId = null; authoritativeEpoch = null; prompted = false; clearSaved()
        mutable.value = AppUiState(origin = state.value.origin, networkConnected = network.value.connected,
            phase = if (network.value.connected) Phase.LOADING else Phase.CONNECTION_ERROR)
        launch { boot(it) }
    }
    private suspend fun checkSession(current: Int) {
        if (generation != current) throw CancellationException("Session changed")
        val binding = bindingId
        val revision = boundRevision
        val origin = state.value.origin
        val valid = withContext(Dispatchers.IO) { synchronized(store) {
            store.revision.value == revision && store.origin == origin &&
                (binding == null || runCatching { store.readSession(origin)?.bindingId }.getOrNull() == binding)
        } }
        if (generation != current) throw CancellationException("Session changed")
        if (!valid) { invalidateSession(); throw CancellationException("Pairing changed") }
    }
    private suspend fun checkRead(current: Int, epoch: Long) {
        checkSession(current)
        if (!network.value.connected || network.value.epoch != epoch) throw CancellationException("Network changed")
    }
    private fun admit(step: String? = null, media: Boolean = false, busy: Boolean = true): Boolean {
        val value = state.value
        val status = network.value
        return value.phase == Phase.READY && live?.phase?.value == LivePhase.LIVE && status.connected && authoritativeEpoch == status.epoch &&
            boundRevision == store.revision.value && bindingId != null && value.authoritative && (!busy || !value.busy) &&
            (step == null || step in value.configurationFresh) && (!media || (!value.editor.readRequired &&
                value.editor.snapshot != null && value.editor.snapshot.`package` == value.dashboard?.`package` && value.editor.snapshot.`package`.status != "completed"))
    }
    private suspend fun checkWrite(current: Int, epoch: Long, step: String? = null, media: Boolean = false) {
        checkRead(current, epoch)
        if (!admit(step, media, busy = false)) throw CancellationException("Write authority changed")
    }
    private fun clearSaved() { saved.keys().toList().forEach { saved.remove<Any>(it) } }
    fun navigate(destination: Destination) {
        if (state.value.phase != Phase.READY) return
        oneoffEpoch++
        saved["destination"] = destination.name
        closeSetup(); mutable.update { it.copy(destination = destination,
            oneoffDecision = it.oneoffDecision.takeIf { destination == Destination.DASHBOARD }, oneoffDecisionIssue = null) }
        if (destination == Destination.ACTIVITY) live?.invalidate(setOf("activity"))
        if (destination == Destination.COMPLETED) refreshCompleted()
        if (liveReading) { live?.invalidate(setOf("*")); return }
        if (destination == Destination.PACKAGE && network.value.connected) refreshEditor()
        if (destination == Destination.SETTINGS && network.value.connected) {
            if (state.value.busy) refreshRequested = true else launch { loadConfiguration(it) }
        }
    }
    fun openSetup() {
        if (state.value.phase != Phase.READY) return
        selectStep(state.value.setup?.checklist?.firstOrNull { it.required && !it.complete }?.key ?: "pairing")
    }
    fun closeSetup() { saved.remove<String>("step"); mutable.update { it.copy(step = null) } }
    fun selectStep(key: String) {
        if (state.value.phase != Phase.READY) return
        saved["step"] = key; mutable.update { it.copy(step = key) }
        if (liveReading) { live?.invalidate(setOf("settings")); return }
        if (network.value.connected) launch { loadConfiguration(it) }
    }

    fun markDirty(step: String) {
        mutable.update { it.copy(dirtySteps = it.dirtySteps + step) }
        saved["dirty_steps"] = ArrayList(state.value.dirtySteps)
    }
    fun setDraft(key: String, value: String, step: String) {
        if (!admit(step, busy = false)) return
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
            "reminders" -> listOf("reminder_interval", "reminder_start", "reminder_end")
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
        val epoch = network.value.epoch
        mutable.update { it.copy(configurationFresh = emptySet()) }
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
            checkRead(current, epoch)
            if (generation == current) {
                remoteDrafts("schedule", mapOf("date" to plan.anchorDate.orEmpty(), "time" to plan.anchorTime.orEmpty(), "enabled" to plan.enabled.toString()), state.value.plan != null && state.value.plan != plan)
                mutable.update { it.copy(plan = plan, configurationFresh = it.configurationFresh + "schedule") }
            }
        }
        load {
            val branding = api().branding()
            checkRead(current, epoch)
            if (generation == current) {
                remoteDrafts("caption_template", mapOf("caption" to branding.captionTemplate.orEmpty()), state.value.branding != null && state.value.branding?.captionTemplate != branding.captionTemplate)
                fun duration(value: Double?) = value?.toBigDecimal()?.stripTrailingZeros()?.toPlainString() ?: "3"
                remoteDrafts("cards", mapOf("intro_duration" to duration(branding.introDuration), "outro_duration" to duration(branding.outroDuration)), state.value.branding != null && state.value.branding != branding)
                mutable.update { it.copy(branding = branding, configurationFresh = it.configurationFresh + setOf("caption_template", "cards", "logo")) }
            }
        }
        load(missingPolicy = true) {
            val policy = api().consent()
            checkRead(current, epoch)
            if (generation == current) mutable.update { it.copy(consent = policy, configurationFresh = it.configurationFresh + "consent", consentAcknowledged = it.consentAcknowledged && it.consent?.version == policy.version && policy.acceptedAt == null) }
        }
        load {
            val instagram = api().instagram()
            checkRead(current, epoch)
            if (generation == current) mutable.update { it.copy(instagram = instagram, configurationFresh = it.configurationFresh + "instagram") }
        }
        if (state.value.destination == Destination.SETTINGS) load {
            val reminders = api().reminders()
            checkRead(current, epoch)
            remoteDrafts("reminders", mapOf("reminder_interval" to reminders.intervalMinutes.toString(),
                "reminder_start" to reminders.deliveryStart, "reminder_end" to reminders.deliveryEnd),
                state.value.reminders != null && state.value.reminders != reminders)
            mutable.update { it.copy(reminders = reminders, configurationFresh = it.configurationFresh + "reminders") }
        }
    }
    fun reloadStep(step: String) {
        if (state.value.phase != Phase.READY || state.value.busy || !network.value.connected) return
        clean(step); launch { loadConfiguration(it) }
    }
    fun acknowledgeConsent(acknowledged: Boolean) {
        if (!admit("consent")) return
        mutable.update { it.copy(consentAcknowledged = acknowledged && it.consent != null && it.consent.acceptedAt == null) }
    }
    private fun mutation(step: String, action: suspend (Int) -> Unit) {
        if (!admit(step)) return
        val epoch = network.value.epoch
        val submittedDrafts = state.value.drafts
        val submittingStep = state.value.step
        launch { current ->
            checkWrite(current, epoch, step)
            action(current)
            checkSession(current)
            if (state.value.drafts == submittedDrafts) clean(step)
            val setup = api().setup()
            if (generation != current) return@launch
            mutable.update { it.copy(setup = setup) }
            persistState(current)
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

    fun refreshCompleted() { live?.invalidate(setOf("completed")) }

    fun selectCompleted(folder: String) {
        if (state.value.completedPackages?.none { it.folderName == folder } != false) return
        mutable.update { it.copy(completedFolder = folder, completedDetail = null) }
        refreshCompleted()
    }

    private suspend fun loadCompleted(current: Int) {
        val epoch = network.value.epoch
        mutable.update { it.copy(completedError = false) }
        try {
            val packages = api().completedPackages(); checkRead(current, epoch)
            val folder = state.value.completedFolder?.takeIf { name -> packages.any { it.folderName == name } }
                ?: packages.firstOrNull()?.folderName
            mutable.update { it.copy(completedPackages = packages, completedFolder = folder,
                completedDetail = it.completedDetail?.takeIf { detail -> detail.folderName == folder }) }
            val detail = folder?.let { api().completedPackage(it) }; checkRead(current, epoch)
            if (state.value.completedFolder == folder) mutable.update { it.copy(completedDetail = detail) }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            checkSession(current)
            mutable.update { it.copy(completedError = true) }
            if (e is ApiFailure && e.status in setOf(401, 426)) throw e
        }
    }
    fun decideOneoff(slot: DashboardSlotOut, skip: Boolean) {
        if (!admit() || state.value.stale || state.value.issue != null || slot.kind != "oneoff" || slot.occurrenceId == null ||
            state.value.oneoffDecision?.let { it.status == "pending" || it.occurrenceId == slot.occurrenceId } == true ||
            OffsetDateTime.parse(slot.dueAt).toInstant() <= Instant.now()) return
        val epoch = network.value.epoch
        val continuation = oneoffEpoch
        launch { current ->
            checkWrite(current, epoch)
            try {
                val result = api().decideOneoff(slot.occurrenceId, OneoffDecisionIn(
                    action = if (skip) "skip" else "review", expectedDueAt = slot.dueAt, confirmed = skip,
                ))
                checkSession(current)
                require(result.occurrenceId == slot.occurrenceId && result.status == if (skip) "skipped" else "pending")
                if (continuation == oneoffEpoch) {
                    oneoffDecisionRevision = state.value.dashboardRevision
                    mutable.update { it.copy(oneoffDecision = result, oneoffDecisionIssue = null) }
                }
            } finally { if (generation == current) live?.invalidate(setOf("dashboard", "activity")) }
        }
    }
    private fun resumeOneoffReview() {
        val value = state.value
        val decision = value.oneoffDecision ?: return
        if (decision.status != "pending" || value.busy || value.stale || !value.authoritative || !network.value.connected ||
            value.destination != Destination.DASHBOARD || value.review.target != null) return
        val dashboard = value.dashboard ?: return
        val actions = dashboard.pendingActions.filter { it.occurrenceId == decision.occurrenceId }
        val slots = dashboard.nextSlots ?: listOfNotNull(dashboard.nextSlot)
        if (value.dashboardRevision > oneoffDecisionRevision && actions.isEmpty() && slots.none { it.occurrenceId == decision.occurrenceId }) {
            mutable.update { it.copy(oneoffDecision = null, oneoffDecisionIssue = ReviewIssue.ALREADY_HANDLED) }; return
        }
        val action = actions.find { it.state == "review_ready" } ?: return
        if (action.reviewId == null) return
        if (decision.packageFolder != null && (action.packageFolder != decision.packageFolder || value.dashboard.`package`?.folderName != decision.packageFolder)) {
            mutable.update { it.copy(oneoffDecision = null, oneoffDecisionIssue = ReviewIssue.PACKAGE_CHANGED) }; return
        }
        openReview(ReviewTarget(reviewId = action.reviewId, packageFolder = action.packageFolder, expectedVersion = action.version))
        saved["review_source_occurrence"] = decision.occurrenceId
    }
    fun changeOneoffDate(slot: DashboardSlotOut, date: LocalDate, time: LocalTime) {
        if (!admit() || state.value.stale || slot.kind != "oneoff" || slot.occurrenceId == null ||
            OffsetDateTime.parse(slot.dueAt).toInstant() <= Instant.now()) return
        val regular = state.value.dashboard?.nextSlots.orEmpty()
            .filter { it.kind == "regular" && OffsetDateTime.parse(it.dueAt).toInstant() > Instant.now() }
            .minByOrNull { OffsetDateTime.parse(it.dueAt).toInstant() }?.dueAt
        val due = futureIstanbulInstant(date, time, Instant.now(), regular)
        if (due == null) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        val epoch = network.value.epoch
        launch { current ->
            checkWrite(current, epoch)
            try { api().changeOneoffDate(slot.occurrenceId, OneoffDateIn(slot.dueAt, due)) }
            finally { if (generation == current) live?.invalidate(setOf("dashboard", "activity")) }
        }
    }
    fun saveCaption(text: String) {
        if (text.isBlank()) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        mutation("caption_template") { api().patchBranding(buildJsonObject { put("caption_template", text) }) }
    }
    fun saveReminders(interval: String, start: String, end: String) {
        val minutes = interval.toIntOrNull()
        val valid = runCatching { LocalTime.parse(start) != LocalTime.parse(end) }.getOrDefault(false)
        if (minutes == null || minutes <= 0 || !valid) { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return }
        mutation("reminders") { api().saveReminders(ReminderPolicyIn(end, start, minutes)) }
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
        if (!admit("instagram")) return
        val epoch = network.value.epoch
        launch { current ->
            checkWrite(current, epoch, "instagram")
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
        if (!network.value.connected) return
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
    fun uploadAsset(field: String, bytes: ByteArray, selectionBinding: String? = currentBinding) {
        require(field in listOf("logo_asset", "intro_asset", "outro_asset"))
        if (selectionBinding == null || selectionBinding != currentBinding) return
        if (state.value.busy) {
            val current = generation
            viewModelScope.launch {
                state.first { !it.busy || generation != current || currentBinding != selectionBinding }
                if (generation == current && currentBinding == selectionBinding) uploadAsset(field, bytes, selectionBinding)
            }
            return
        }
        if (!admit(if (field == "logo_asset") "logo" else "cards")) return
        if (bytes.isEmpty() || bytes.size > 10 * 1024 * 1024 || (field != "logo_asset" && !state.value.drafts[field.replace("_asset", "_duration")].isNullOrEmpty() && cardDuration(field) == null)) {
            mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) }; return
        }
        mutation(if (field == "logo_asset") "logo" else "cards") { current ->
            val epoch = network.value.epoch
            val uploaded = api().uploadBranding(bytes)
            checkSession(current)
            saved["pending_$field"] = uploaded.asset; saved["preview_$field"] = uploaded.previewUrl
            mutable.update { it.copy(pendingAssets = it.pendingAssets + (field to uploaded)) }
            installAsset(field, uploaded, current, epoch)
        }
    }
    private fun cardDuration(field: String): Double? = state.value.drafts[field.replace("_asset", "_duration")]?.toDoubleOrNull()?.takeIf { it.isFinite() && it > 0 && it % 1.0 == 0.0 }
    private suspend fun installAsset(field: String, uploaded: BrandingAssetOut, current: Int, epoch: Long = network.value.epoch) {
        checkWrite(current, epoch, if (field == "logo_asset") "logo" else "cards")
        val changes = buildJsonObject {
            put(field, uploaded.asset)
            if (field != "logo_asset") {
                val key = field.replace("_asset", "_duration")
                val value = cardDuration(field)
                require(state.value.drafts[key].isNullOrEmpty() || value != null)
                put(key, value?.let(::JsonPrimitive) ?: JsonNull)
            }
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
    fun clearCard(field: String) {
        require(field in setOf("intro_asset", "outro_asset"))
        if (!state.value.canConfigure("cards")) return
        val branding = state.value.branding ?: return
        saved.remove<String>("pending_$field"); saved.remove<String>("preview_$field")
        mutable.update { it.copy(pendingAssets = it.pendingAssets - field) }
        setDraft(field.replace("_asset", "_duration"), "", "cards")
        if ((if (field == "intro_asset") branding.introAsset else branding.outroAsset) != null) {
            saveCards(if (field == "intro_asset") null else branding.introAsset,
                if (field == "intro_asset") null else branding.introDuration,
                if (field == "outro_asset") null else branding.outroAsset,
                if (field == "outro_asset") null else branding.outroDuration)
        }
    }
    fun saveCards(introAsset: String?, introDuration: Double?, outroAsset: String?, outroDuration: Double?) {
        fun valid(asset: String?, duration: Double?) = if (asset == null) duration == null else duration == null || duration.isFinite() && duration > 0 && duration % 1.0 == 0.0
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
        require(state.value.phase == Phase.READY && network.value.connected)
        val current = generation
        val bytes = try { api().preview(path) }
        catch (e: ApiFailure) {
            if (generation == current && (e.status == 401 || e.status == 426)) failure(e)
            throw e
        }
        if (generation != current) throw CancellationException("Session changed")
        return bytes
    }
    suspend fun downloadMediaPreview(previewUrl: String, destination: File) {
        require(state.value.phase == Phase.READY && network.value.connected)
        val current = generation
        try {
            api().downloadReviewPreview(previewUrl, destination)
        } catch (e: ApiFailure) {
            destination.delete()
            if (generation == current && (e.status == 401 || e.status == 426)) failure(e)
            throw e
        } catch (e: Exception) {
            destination.delete()
            throw e
        }
        if (generation != current) {
            destination.delete()
            throw CancellationException("Session changed")
        }
    }
    fun refreshEditor() {
        if (state.value.phase == Phase.READY && network.value.connected) launch { loadEditor(it, explicit = true) }
    }
    private suspend fun loadEditor(current: Int, explicit: Boolean = false, expected: ActiveEditorOut? = null, savedTrims: Boolean = false) {
        val epoch = network.value.epoch
        try {
            val snapshot = api().mediaEditor()
            checkRead(current, epoch)
            if (snapshot.`package` != state.value.dashboard?.`package`) {
                mutable.update { it.copy(editor = it.editor.copy(readRequired = true, issue = EditorIssue.CONFLICT), editorFetchedAt = null) }
                persistState(current)
                return
            }
            val old = state.value.editor
            reconcileClearRead(explicit)
            val accepted = old.accept(snapshot, explicit, expected, savedTrims)
            mutable.update { it.copy(editor = accepted, editorFetchedAt = now()) }
            if (old.storedDraft != accepted.storedDraft && draftStore != null) {
                persistEditor(accepted, old.draftPackageId ?: old.snapshot?.`package`?.id ?: snapshot.`package`.id).await()
            }
            persistState(current)
        } catch (e: ApiFailure) {
            checkSession(current)
            if (e.status != 404) {
                mutable.update { it.copy(editor = it.editor.copy(readRequired = true, issue = EditorIssue.READ)) }
                throw e
            }
            reconcileClearRead(explicit)
            mutable.update { it.copy(editor = if (it.editor.dirty) it.editor.copy(snapshot = null, readRequired = true, issue = EditorIssue.CONFLICT) else MediaEditorState(), editorFetchedAt = now()) }
            persistState(current)
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            checkSession(current)
            mutable.update { it.copy(editor = it.editor.copy(readRequired = true, issue = EditorIssue.READ)) }
            throw e
        }
    }
    fun editRanges(id: String, ranges: List<RangeInput>) {
        if (!admit(media = true) || state.value.editor.persistenceIssue != null) return
        if (state.value.editor.snapshot?.media?.none { it.mediaId == id && it.isVideo && it.status == "finalized" } != false) return
        persistEditor(state.value.editor.edit(id, ranges))
    }
    fun editPhotoDuration(id: String, value: String) {
        if (!admit(media = true) || state.value.editor.persistenceIssue != null) return
        if (state.value.editor.snapshot?.media?.none { it.mediaId == id && !it.isVideo && it.status == "finalized" } != false) return
        persistEditor(state.value.editor.editPhotoDuration(id, value))
    }
    fun discardMedia(id: String) {
        val editor = state.value.editor
        if (!admit() || editor.readRequired && editor.issue in setOf(EditorIssue.READ, EditorIssue.UNCERTAIN)) return
        persistEditor(editor.discard(id))
    }
    fun discardReplacedMediaDraft() {
        val editor = state.value.editor
        if (!admit() || editor.readRequired && editor.issue in setOf(EditorIssue.READ, EditorIssue.UNCERTAIN)) return
        val clean = editor.discard()
        val oldPackage = editor.draftPackageId
        val packageId = editor.snapshot?.`package`?.id
        if (oldPackage == null || packageId == null || oldPackage == packageId) return
        val current = generation
        viewModelScope.launch {
            // Remove the replaced package's draft before binding this editor to the new package.
            if (persistEditor(editor.copy(storedDraft = null, draftPackageId = oldPackage)).await()) {
                if (generation == current) persistEditor(clean.copy(draftPackageId = packageId))
            } else if (generation == current) {
                mutable.update { it.copy(editor = editor.copy(persistenceIssue = it.editor.persistenceIssue)) }
            }
        }
    }
    private fun mediaMutation(expected: ActiveEditorOut, savedTrims: Boolean = false, discardId: String? = null,
        refreshOnConflict: Boolean = false, action: suspend (DojoApi, String) -> Any?) {
        val editor = state.value.editor
        if (!admit(media = true) || editor.snapshot == null || editor.persistenceIssue != null) return
        val epoch = network.value.epoch
        val folder = editor.snapshot.`package`.folderName
        launch { current ->
            try {
                checkWrite(current, epoch, media = true)
                val draft = editor.storedDraft ?: StoredDraft(folderName = folder, baseContentRevision = editor.snapshot.contentRevision)
                if (!persistEditor(state.value.editor.copy(storedDraft = draft.copy(uncertain = true,
                    pendingRemovals = if (discardId == null) draft.pendingRemovals else draft.pendingRemovals + discardId),
                    draftPackageId = editor.draftPackageId ?: editor.snapshot.`package`.id)).await()) return@launch
                checkWrite(current, epoch, media = true)
                val response = action(api(), folder)
                checkSession(current)
                if (discardId != null) persistEditor(state.value.editor.discard(discardId)).await()
                if (response is ActiveEditorOut) {
                    val accepted = state.value.editor.accept(response, expected = expected)
                    persistEditor(accepted, editor.snapshot.`package`.id).await()
                }
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
                if (e is ApiFailure && e.status in setOf(404, 409, 422)) {
                    val retained = state.value.editor.storedDraft
                    if (retained != null) persistEditor(state.value.editor.copy(storedDraft = retained.copy(uncertain = false,
                        pendingRemovals = if (discardId == null) retained.pendingRemovals else retained.pendingRemovals - discardId))).await()
                }
                if (refreshOnConflict && e is ApiFailure && e.status == 409) loadEditor(current, explicit = true)
            }
        }
    }
    fun reorderMedia(order: List<String>) {
        val snapshot = state.value.editor.snapshot ?: return
        if (order == snapshot.montage.order || order.size != order.toSet().size || order.toSet() != snapshot.montage.order.toSet()) return
        mediaMutation(snapshot.copy(montage = snapshot.montage.copy(order = order))) { api, folder -> api.orderMedia(folder, order, snapshot.packageRevision()) }
    }
    fun removeMedia(id: String, confirmedDiscard: Boolean = false) {
        val snapshot = state.value.editor.snapshot ?: return
        if (state.value.editor.isDirty(id) && !confirmedDiscard) return
        if (snapshot.media.none { it.mediaId == id && it.status == "finalized" }) return
        val expected = snapshot.copy(media = snapshot.media.map { if (it.mediaId == id) it.copy(status = "removed") else it },
            montage = snapshot.montage.copy(order = snapshot.montage.order.filter { it != id }))
        mediaMutation(expected, discardId = id) { api, folder -> api.removeMedia(folder, id, snapshot.packageRevision()) }
    }
    fun restoreMedia(id: String) {
        val snapshot = state.value.editor.snapshot ?: return
        val media = snapshot.media.find { it.mediaId == id && it.status == "removed" } ?: return
        val order = snapshot.montage.order.toMutableList().apply { add((media.removedPosition ?: size).coerceIn(0, size), id) }
        val expected = snapshot.copy(media = snapshot.media.map { if (it.mediaId == id) it.copy(status = "finalized") else it }, montage = snapshot.montage.copy(order = order))
        mediaMutation(expected) { api, folder -> api.restoreMedia(folder, id, snapshot.packageRevision()) }
    }
    fun saveMedia(id: String) {
        val editor = state.value.editor
        if (!editor.canSave(id)) return
        val snapshot = editor.snapshot ?: return
        val draft = editor.storedDraft ?: return
        val media = snapshot.media.find { it.mediaId == id } ?: return
        val key = "${if (media.isVideo) "video" else "photo"}:$id"
        val group = draft.groups[key] ?: return
        mediaMutation(snapshot, savedTrims = true) { api, folder ->
            api.savePackageEdits(PackageEditIn(baseContentRevision = draft.baseContentRevision,
                changes = listOf(GroupEditIn(base = group.base, key = key, proposed = group.proposed)),
                expectedFolderName = folder, expectedPackageId = snapshot.`package`.id))
        }
    }
    fun retrySectionPreview(id: String) {
        val snapshot = state.value.editor.snapshot ?: return
        val preview = snapshot.media.find { it.mediaId == id && it.status == "finalized" }?.sectionPreview ?: return
        if (preview.status != "failed" || preview.generation == null) return
        mediaMutation(snapshot, refreshOnConflict = true) { api, folder -> api.retrySectionPreview(id,
            SectionPreviewRetryIn(expectedFolderName = folder, expectedPackageId = snapshot.`package`.id, expectedGeneration = preview.generation)) }
    }
    fun renderActivePackage() {
        val snapshot = state.value.editor.snapshot ?: return
        if (snapshot.renderStatus in setOf("queued", "processing") || snapshot.montage.order.isEmpty() || snapshot.montage.overLimit || !snapshot.montage.durationComplete) return
        mediaMutation(snapshot) { api, folder -> api.renderPackage(folder, snapshot.packageRevision(), retry = snapshot.renderStatus == "failed") }
    }
    fun clearActivePackage(confirmed: Boolean) {
        if (!confirmed || !admit() || state.value.editor.persistenceIssue != null) return
        val editor = state.value.editor
        val pending = saved.get<Int>("clear_package_id")
        if (pending != null && (saved.get<String>("clear_origin") != state.value.origin || saved.get<String>("clear_binding") != bindingId)) {
            forgetClearTarget(); return
        }
        if (pending == null && !admit(media = true) || pending != null && state.value.clearReadRequired) return
        val snapshot = editor.snapshot
        val id = pending ?: snapshot?.`package`?.id ?: return
        val folder = saved.get<String>("clear_package_folder") ?: snapshot?.`package`?.folderName ?: return
        val revision = saved.get<Long>("clear_package_revision") ?: snapshot?.contentRevision ?: return
        val ownsDraft = (editor.draftPackageId ?: snapshot?.`package`?.id) == id
        saved["clear_package_id"] = id; saved["clear_package_folder"] = folder; saved["clear_package_revision"] = revision
        saved["clear_origin"] = state.value.origin; saved["clear_binding"] = bindingId
        saved["clear_requires_read"] = true
        mutable.update { it.copy(pendingClearFolder = folder, clearReadRequired = true) }
        val epoch = network.value.epoch
        launch { current ->
            try {
                checkWrite(current, epoch)
                if (ownsDraft) {
                    val draft = editor.storedDraft ?: StoredDraft(folderName = folder, baseContentRevision = revision)
                    if (!persistEditor(editor.copy(storedDraft = draft.copy(uncertain = true), draftPackageId = id,
                        readRequired = true, issue = EditorIssue.UNCERTAIN), id).await()) return@launch
                }
                checkWrite(current, epoch)
                api().clearPackage(ClearPackageIn(confirmed = true, expectedFolderName = folder,
                    expectedPackageId = id), PackageRevision(id, revision))
                checkSession(current)
            } catch (error: CancellationException) { throw error }
            catch (error: Exception) {
                checkSession(current)
                if (error is ApiFailure && error.status in setOf(401, 426)) throw error
                // A 404 after the identity-bound clear route checked its cleanup journal
                // proves that neither the package nor unfinished cleanup remains.
                if (error !is ApiFailure || error.status != 404) {
                    val definite = error is ApiFailure && error.status in setOf(409, 422)
                    mutable.update { it.copy(editor = it.editor.copy(readRequired = true,
                        issue = if (definite) EditorIssue.CONFLICT else EditorIssue.UNCERTAIN)) }
                    if (definite) {
                        forgetClearTarget()
                        val retained = state.value.editor.storedDraft
                        if (ownsDraft && retained != null) persistEditor(state.value.editor.copy(storedDraft = retained.copy(uncertain = false)), id).await()
                    }
                    return@launch
                }
            }
            if (ownsDraft) {
                if (!persistEditor(MediaEditorState(draftPackageId = id), id).await()) return@launch
            }
            else clearCapturedDraft(current, id)
            forgetClearTarget()
            val dashboard = api().dashboard(); checkRead(current, epoch)
            mutable.update { it.copy(dashboard = dashboard, dashboardFetchedAt = now()) }
            loadEditor(current, explicit = true)
        }
    }
    private fun forgetClearTarget() {
        saved.remove<Int>("clear_package_id"); saved.remove<String>("clear_package_folder"); saved.remove<Long>("clear_package_revision")
        saved.remove<Boolean>("clear_requires_read")
        saved.remove<String>("clear_origin"); saved.remove<String>("clear_binding")
        mutable.update { it.copy(pendingClearFolder = null, clearReadRequired = false) }
    }
    private suspend fun clearCapturedDraft(current: Int, id: Int) {
        val origin = state.value.origin; val binding = bindingId ?: throw CancellationException("Session changed")
        draftWrite?.await()
        withContext(Dispatchers.IO) { synchronized(store) {
            if (generation != current || store.readSession(origin)?.bindingId != binding) throw CancellationException("Session changed")
            draftStore?.clear(origin, binding, id)
        } }
    }
    private fun reconcileClearRead(explicit: Boolean) {
        if (!explicit || saved.get<Int>("clear_package_id") == null) return
        saved["clear_requires_read"] = false
        mutable.update { it.copy(clearReadRequired = false) }
    }
    fun pickerFailed() { mutable.update { it.copy(issue = UiIssue.INVALID_INPUT) } }
    private fun clearNotificationSaved() { saved.keys().filter { it.startsWith("notification_") }.forEach { saved.remove<Any>(it) } }
    fun openNotification(target: NotificationTarget, origin: String, bindingId: String) {
        if (parseNotificationTarget(target.data()) != target || origin != state.value.origin || bindingId.isBlank() ||
            runCatching { store.readSession(origin)?.bindingId }.getOrNull() != bindingId) return
        saved["notification_data"] = JsonObject(target.data().mapValues { JsonPrimitive(it.value) }).toString()
        saved["notification_origin"] = origin
        saved["notification_binding"] = bindingId
        consumeNotification()
    }
    private fun consumeNotification() {
        if (state.value.phase != Phase.READY) return
        val raw = saved.get<String>("notification_data") ?: return
        val origin = saved.get<String>("notification_origin")
        val binding = saved.get<String>("notification_binding")
        val target = runCatching { parseNotificationTarget(Json.parseToJsonElement(raw).jsonObject.mapValues { it.value.jsonPrimitive.content }) }.getOrNull()
        clearNotificationSaved()
        if (target == null || origin != state.value.origin || binding != bindingId ||
            runCatching { store.readSession(state.value.origin)?.bindingId }.getOrNull() != binding) return
        if (target.type.startsWith("publication_")) {
            closeReview(); navigate(Destination.ACTIVITY)
            mutable.update { it.copy(outcomePackage = target.packageFolder) }
            refresh()
        } else {
            closeSetup()
            openReview(ReviewTarget(reviewId = target.reviewId, occurrenceId = target.occurrenceId,
                packageFolder = target.packageFolder, expectedVersion = target.reviewVersion, action = target.action))
        }
    }
    fun observePushFailure(failure: PushFailure) {
        if (failure.origin != state.value.origin || failure.bindingId != bindingId ||
            state.value.phase !in setOf(Phase.READY, Phase.LOADING)) return
        val current = generation; val revision = boundRevision
        if (failure.status in setOf(401, 426)) viewModelScope.launch {
            if (generation == current && store.revision.value == revision && bindingId == failure.bindingId)
                failure(ApiFailure(failure.status, failure.updateUrl))
        }
    }
    val currentBindingId: String? get() = bindingId?.takeIf {
        boundRevision == store.revision.value
    }
    fun observePushReceipt(receipt: PushReceipt) {
        if (receipt.origin == state.value.origin && receipt.bindingId == currentBindingId && state.value.phase == Phase.READY) {
            if (state.value.busy) pendingPushRefresh = true else refresh()
        }
    }

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
        mutable.update { it.copy(review = ReviewState(target = target, continuing = saved.get<Boolean>("review_continuing") ?: false)) }
    }
    private fun clearReviewSaved() { saved.keys().filter { it.startsWith("review_") }.forEach { saved.remove<Any>(it) } }
    fun openReview(target: ReviewTarget) {
        if (state.value.phase != Phase.READY || !target.valid) return
        oneoffEpoch++
        reviewEpoch++; reviewJob?.cancel()
        clearReviewSaved()
        saved["review_owner"] = state.value.destination.name
        saveReviewTarget(target)
        mutable.update { it.copy(review = ReviewState(target = target), oneoffDecision = null, oneoffDecisionIssue = null) }
        if (target.action == ReviewAction.UPLOAD) navigate(Destination.PACKAGE)
        refreshReview()
    }
    fun closeReview() {
        reviewEpoch++; reviewJob?.cancel(); reviewJob = null
        val owner = Destination.entries.firstOrNull { it.name == saved.get<String>("review_owner") } ?: state.value.destination
        clearReviewSaved(); saved["destination"] = owner.name
        mutable.update { it.copy(review = ReviewState(), destination = owner) }
    }
    private suspend fun checkReview(current: Int, epoch: Int) {
        checkSession(current)
        if (epoch != reviewEpoch || state.value.phase != Phase.READY) throw CancellationException("Review changed")
    }
    private fun reviewWork(mutation: Boolean = false, action: suspend (Int, Int) -> Unit) {
        if (liveReading) { if (!mutation) live?.invalidate(setOf("publication")); return }
        if (state.value.phase != Phase.READY || !network.value.connected || state.value.review.busy || state.value.review.target == null ||
            mutation && (!admit() || state.value.stale)) return
        val current = generation
        val epoch = reviewEpoch
        val networkEpoch = network.value.epoch
        mutable.update { it.copy(review = it.review.copy(busy = true)) }
        reviewJob = viewModelScope.launch {
            try {
                checkReview(current, epoch)
                if (mutation) checkWrite(current, networkEpoch) else checkRead(current, networkEpoch)
                action(current, epoch)
            }
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
    fun refreshReview() {
        if (live?.phase?.value == LivePhase.SYNCING) { live?.invalidate(setOf("*")); return }
        reviewWork { current, epoch -> loadReview(current, epoch) }
    }
    fun refreshReviewOnInvalidation() {
        val review = state.value.review
        if (review.target != null && !review.busy && review.issue == null &&
            (review.detail?.review?.status in setOf("pending", "failed", "uncertain", "publishing") || review.target.occurrenceId != null)) refreshReview()
    }
    suspend fun downloadReviewPreview(id: Int, revision: String, destination: File) {
        val current = generation
        val epoch = reviewEpoch
        val networkEpoch = network.value.epoch
        suspend fun requirePreview(): String {
            checkReview(current, epoch)
            checkRead(current, networkEpoch)
            val review = state.value.review
            val detail = requireNotNull(review.detail)
            require(review.target?.reviewId == id && detail.review.id == id &&
                detail.review.revisionDigest == revision && detail.renderReady && review.issue == null && !review.readRequired)
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
        val networkEpoch = network.value.epoch
        checkRead(current, networkEpoch)
        val target = state.value.review.target ?: return
        val transport = api()
        if (target.reviewId != null) {
            val detail = transport.review(target.reviewId)
            checkReview(current, epoch)
            checkRead(current, networkEpoch)
            require(detail.review.id > 0 && detail.review.version > 0 && detail.review.revisionDigest.isNotBlank() &&
                 detail.review.packageFolder.isNotBlank() && detail.review.status in setOf("pending", "failed", "uncertain", "publishing", "approved", "skipped", "rescheduled"))
            saved.get<Int>("review_source_occurrence")?.let { require(detail.review.occurrenceId == it) }
            val source = saved.get<Int>("review_source_occurrence")
            if (source != null && detail.review.status in setOf("pending", "failed", "uncertain") && !detail.renderReady) {
                val next = ReviewTarget(occurrenceId = source, packageFolder = target.packageFolder, action = ReviewAction.UPLOAD)
                saveReviewTarget(next); saved["review_continuing"] = true
                mutable.update { it.copy(review = ReviewState(target = next, busy = true, continuing = true)) }
                loadReview(current, epoch); return
            }
            val issue = when {
                detail.review.id != target.reviewId || target.packageFolder != null && target.packageFolder != detail.review.packageFolder -> ReviewIssue.STALE
                detail.review.status !in setOf("pending", "failed", "uncertain", "publishing") -> ReviewIssue.ALREADY_HANDLED
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
            checkRead(current, networkEpoch)
            val matches = dashboard.pendingActions.filter { it.occurrenceId == target.occurrenceId }
            val pending = matches.find { it.packageFolder == target.packageFolder && it.state == "review_ready" } ?: matches.firstOrNull()
            val issue = when {
                pending == null -> ReviewIssue.ALREADY_HANDLED
                pending.packageFolder != target.packageFolder || dashboard.`package`?.folderName != target.packageFolder -> ReviewIssue.PACKAGE_CHANGED
                pending.state !in setOf("empty_package", "preparing", "review_ready") -> ReviewIssue.STALE
                else -> null
            }
            mutable.update {
                val changedPackage = it.editor.snapshot?.`package` != dashboard.`package`
                it.copy(dashboard = dashboard, dashboardRevision = it.dashboardRevision + 1, dashboardFetchedAt = now(),
                    editor = if (changedPackage && it.editor.storedDraft == null) MediaEditorState() else it.editor,
                    editorFetchedAt = if (changedPackage) null else it.editorFetchedAt,
                    review = it.review.copy(readRequired = issue != null || pending?.state != "empty_package",
                issue = issue, continuing = it.review.continuing && issue == null,
                nextRegularAt = it.review.nextRegularAt ?: dashboard.nextSlot?.takeIf { slot -> slot.kind == "regular" }?.dueAt)) }
            persistState(current)
            if (issue != null) { saved["review_continuing"] = false; return }
            if (pending?.reviewId != null && pending.state == "review_ready") {
                val detail = transport.review(pending.reviewId)
                checkReview(current, epoch)
                checkRead(current, networkEpoch)
                if ((detail.renderReady || detail.review.status == "publishing") && detail.review.status in setOf("pending", "failed", "uncertain", "publishing") && detail.review.id == pending.reviewId &&
                    detail.review.occurrenceId == target.occurrenceId && detail.review.packageFolder == target.packageFolder &&
                    detail.review.version == pending.version && detail.review.version > 0 && detail.review.revisionDigest.isNotBlank()) {
                    saved["review_source_occurrence"] = target.occurrenceId
                    val next = ReviewTarget(reviewId = pending.reviewId, packageFolder = target.packageFolder, expectedVersion = pending.version)
                    saveReviewTarget(next); saved["review_continuing"] = false
                    mutable.update { it.copy(review = ReviewState(target = next, detail = detail, busy = true, nextRegularAt = detail.nextRegularAt)) }
                    return
                }
            }
            if (target.action == ReviewAction.UPLOAD || state.value.review.continuing) {
                val snapshot = transport.mediaEditor()
                checkReview(current, epoch)
                checkRead(current, networkEpoch)
                if (snapshot.`package`.folderName != target.packageFolder || snapshot.`package`.status != "active") {
                    saved["review_continuing"] = false
                    mutable.update { it.copy(review = it.review.copy(issue = ReviewIssue.PACKAGE_CHANGED, readRequired = true, continuing = false)) }
                } else {
                    val failed = snapshot.renderStatus == "failed"
                    mutable.update { it.copy(editor = it.editor.accept(snapshot), editorFetchedAt = now(), review = it.review.copy(uploadPackageId = snapshot.`package`.id, issue = if (failed) ReviewIssue.RENDER_FAILED else null,
                        continuing = it.review.continuing && !failed)) }
                    persistState(current)
                    if (failed) saved["review_continuing"] = false
                }
            }
        }
    }
    fun requestReviewAction(action: ReviewAction) {
        val review = state.value.review
        val target = review.target ?: return
        if (!admit(busy = false) || review.busy) return
        val updated = target.copy(action = action)
        saveReviewTarget(updated)
        mutable.update { it.copy(review = it.review.copy(target = updated)) }
        if (action == ReviewAction.UPLOAD && target.occurrenceId != null) navigate(Destination.PACKAGE)
    }
    val reviewUploadPackageId: Int? get() {
        val current = state.value
        val review = current.review
        if (!admit() || current.stale || review.busy ||
            review.target?.action != ReviewAction.UPLOAD || review.target.occurrenceId == null ||
            review.issue !in setOf(null, ReviewIssue.MEDIA_REQUIRED, ReviewIssue.UPLOAD_PENDING, ReviewIssue.RENDER_FAILED)) return null
        return review.uploadPackageId
    }
    fun enqueueReviewUploads(expectedPackageId: Int, enqueue: (Int) -> Unit) {
        if (reviewUploadPackageId != expectedPackageId) return
        val networkEpoch = network.value.epoch
        reviewWork { current, epoch ->
            loadReview(current, epoch)
            checkWrite(current, networkEpoch)
            val review = state.value.review
            if (!state.value.stale && review.target?.action == ReviewAction.UPLOAD &&
                review.uploadPackageId == expectedPackageId && review.issue in setOf(null, ReviewIssue.RENDER_FAILED)) enqueue(expectedPackageId)
        }
    }
    fun continueReview(uploadRows: List<UploadRecord>, retry: Boolean = false) {
        val review = state.value.review
        if (!admit() || review.busy || review.target?.occurrenceId == null ||
            review.target.action != ReviewAction.UPLOAD || review.continuing && !retry ||
            review.issue in setOf(ReviewIssue.UNCERTAIN, ReviewIssue.PACKAGE_CHANGED, ReviewIssue.ALREADY_HANDLED, ReviewIssue.NOT_FOUND)) return
        if (uploadRows.any { it.origin == state.value.origin && it.bindingId == bindingId && it.phase !in setOf(UploadPhase.FINALIZED, UploadPhase.SKIPPED) }) {
            mutable.update { it.copy(review = it.review.copy(issue = ReviewIssue.UPLOAD_PENDING)) }; return
        }
        val networkEpoch = network.value.epoch
        reviewWork(mutation = true) { current, epoch ->
            loadReview(current, epoch)
            checkWrite(current, networkEpoch)
            val fresh = state.value.review
            if (fresh.target?.reviewId != null || fresh.issue != null && !(fresh.issue == ReviewIssue.RENDER_FAILED && retry)) return@reviewWork
            val snapshot = state.value.editor.snapshot ?: return@reviewWork
            if (state.value.editor.dirty || state.value.editor.readRequired || snapshot.montage.order.isEmpty() ||
                snapshot.media.none { it.status == "finalized" && it.mediaId in snapshot.montage.order } ||
                !snapshot.montage.durationComplete || snapshot.montage.overLimit) {
                mutable.update { it.copy(review = it.review.copy(issue = ReviewIssue.MEDIA_REQUIRED)) }; return@reviewWork
            }
            if (snapshot.renderStatus !in setOf("ready", "queued", "processing") || retry) {
                try { api().renderPackage(requireNotNull(fresh.target?.packageFolder), snapshot.packageRevision(), retry) }
                catch (e: ApiFailure) {
                    if (e.status == 409) {
                        checkReview(current, epoch)
                        mutable.update { it.copy(review = it.review.copy(issue = ReviewIssue.PACKAGE_CHANGED, readRequired = true, continuing = false)) }
                        return@reviewWork
                    }
                    throw e
                }
            }
            checkReview(current, epoch)
            saved["review_continuing"] = true
            mutable.update { it.copy(review = it.review.copy(continuing = true, readRequired = true, issue = null)) }
        }
    }
    fun markReviewPreviewReady(id: Int, revision: String, ready: Boolean) {
        val review = state.value.review
        val detail = review.detail ?: return
        if (state.value.phase != Phase.READY || review.target?.reviewId != id || detail.review.id != id ||
            detail.review.revisionDigest != revision || ready && (!admit(busy = false) || review.readRequired || !detail.renderReady || review.issue != null)) return
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
        val due = futureIstanbulInstant(date, time, Instant.now(), review.nextRegularAt)
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
                refreshReviewDashboard(current, epoch)
            } catch (e: ApiFailure) {
                checkReview(current, epoch)
                if (e.status == 409) {
                    loadReview(current, epoch)
                    mutable.update { it.copy(review = it.review.copy(readRequired = true,
                        issue = if (it.review.detail?.review?.status?.let { status -> status !in setOf("pending", "failed", "uncertain", "publishing") } == true)
                             ReviewIssue.ALREADY_HANDLED else ReviewIssue.STALE)) }
                    refreshReviewDashboard(current, epoch)
                } else throw e
            }
        }
    }
    private suspend fun refreshReviewDashboard(current: Int, epoch: Int) {
        val networkEpoch = network.value.epoch
        try {
            val dashboard = api().dashboard()
            checkReview(current, epoch)
            checkRead(current, networkEpoch)
            mutable.update {
                val changedPackage = it.editor.snapshot?.`package` != dashboard.`package`
                it.copy(dashboard = dashboard, dashboardRevision = it.dashboardRevision + 1, dashboardFetchedAt = now(), stale = false,
                    editor = if (changedPackage) MediaEditorState() else it.editor,
                    editorFetchedAt = if (changedPackage) null else it.editorFetchedAt)
            }
            persistState(current)
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            checkReview(current, epoch)
            if (e is ApiFailure && e.status in setOf(401, 426)) throw e
            mutable.update { it.copy(stale = true, issue = UiIssue.NETWORK) }
        }
    }
}

private class PolicyChanged : Exception()

fun safeExternalUrl(raw: String): String? = try {
    val uri = URI(raw)
    raw.takeIf { uri.scheme == "https" && !uri.host.isNullOrBlank() && uri.rawUserInfo == null }
} catch (_: Exception) { null }
