package com.dojo.aisomedo.uploads

import android.content.Context
import android.net.Uri
import com.dojo.aisomedo.BuildConfig
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.offline.*
import com.dojo.aisomedo.safeExternalUrl
import com.dojo.aisomedo.auth.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.OkHttpClient
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import java.io.File

class UploadRuntime private constructor(private val context: Context) {
    val network = NetworkMonitor(context)
    val snapshots = SnapshotStore(context.noBackupFilesDir.resolve("offline"))
    val sessionStore = SessionStore(context.noBackupFilesDir.resolve("session")) { androidKeystoreKey() }
    private val store = UploadStore(context.noBackupFilesDir.resolve("uploads"))
    private val source = UploadSource(context.contentResolver)
    private val scheduler = UploadScheduler(context)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val actions = Mutex()
    private val queue = Mutex()
    private val blocked = ConcurrentHashMap.newKeySet<String>()
    @Volatile private var attached: Triple<String, Int, String>? = null
    private val mutableWriteAccess = MutableStateFlow<String?>(null)
    val writeAccess = mutableWriteAccess.asStateFlow()
    @Volatile private var writeBinding: String? = null
        set(value) { field = value; publishWriteAccess() }
    @Volatile private var writeEpoch: Long? = null
    @Volatile private var updateBinding: String? = null
    private val accessRevision = AtomicLong()
    private val visibleRows = MutableStateFlow<List<UploadRecord>>(emptyList())
    val rows = visibleRows.asStateFlow()
    private val currentIssue = MutableStateFlow<UploadIssue?>(null)
    val issue = currentIssue.asStateFlow()
    private val mutableResolving = MutableStateFlow<String?>(null)
    val resolvingId = mutableResolving.asStateFlow()
    @Volatile var failureBinding: String? = null
        private set
    private val http = OkHttpClient()
    private val engine = UploadEngine(store, source::open, { row ->
        if (row.bindingId in blocked) null else sessionStore.readSession(row.origin)?.takeIf { it.bindingId == row.bindingId }
    }, { row, credential -> DojoApi(row.origin, credential.token, BuildConfig.VERSION_CODE, http) }, System::currentTimeMillis,
        { network.state.value.connected }, ::recordUpdateRequired)
    init {
        // Remove only this feature's abandoned private previews after process death.
        context.cacheDir.resolve("conflict-previews").listFiles()?.filter { it.isFile }?.forEach { it.delete() }
        scope.launch { store.rows.collect { publishRows() } }
        scope.launch {
            var observedEpoch = network.state.value.epoch
            network.state.collect { status ->
                if (status.epoch != observedEpoch || !status.connected) {
                    observedEpoch = status.epoch
                    accessRevision.incrementAndGet(); writeBinding = null; writeEpoch = null; engine.suspendTransfers()
                }
                if (!status.connected) Unit
                else {
                    val origin = sessionStore.origin ?: return@collect
                    val binding = runCatching { sessionStore.readSession(origin)?.bindingId }.getOrNull() ?: return@collect
                    if (pending(binding) && !unsupported(origin, binding)) {
                        if (!scheduler.wake(binding)) schedulingFailed(binding, UploadIssue.SCHEDULING)
                    }
                }
            }
        }
    }

    fun setWriteAccess(origin: String, bindingId: String?, allowed: Boolean) {
        val revision = accessRevision.incrementAndGet()
        val epoch = network.state.value.epoch
        if (!allowed || bindingId == null) { writeBinding = null; writeEpoch = null; return }
        launchAction {
            if (revision != accessRevision.get() || !network.state.value.connected || network.state.value.epoch != epoch || sessionStore.readSession(origin)?.bindingId != bindingId) return@launchAction
            val cached = snapshots.read(origin, bindingId)
            if (cached?.rejectedVersionCode == BuildConfig.VERSION_CODE || cached?.compat?.let { UpdatePolicy.isOutdated(BuildConfig.VERSION_CODE, it.androidMinVersionCode) } == true) return@launchAction
            if (updateBinding == bindingId) {
                if (cached?.compat == null) return@launchAction
                updateBinding = null; blocked.remove(bindingId)
            }
            if (matches(bindingId)) { writeEpoch = epoch; writeBinding = bindingId }
        }
    }
    private fun canWrite(binding: String) = network.state.value.connected && writeEpoch == network.state.value.epoch && writeBinding == binding && matches(binding) && updateBinding != binding
    private fun publishWriteAccess() { mutableWriteAccess.value = attached?.third?.takeIf(::canWrite) }
    private data class SelectionFence(val binding: String, val epoch: Long, val sessionRevision: Long)
    private fun selectionFence(binding: String) = SelectionFence(binding, network.state.value.epoch, sessionStore.revision.value)
    private fun selectionCurrent(fence: SelectionFence) = network.state.value.connected && network.state.value.epoch == fence.epoch &&
        sessionStore.revision.value == fence.sessionRevision && attached?.third == fence.binding && matches(fence.binding)
    private suspend fun withSelectionAccess(fence: SelectionFence, commit: suspend () -> Boolean) = awaitSelectionCommit(
        combine(writeAccess, network.state, sessionStore.revision, issue) { ready, _, _, _ ->
            when {
                !selectionCurrent(fence) -> SelectionAvailability.INVALID
                ready == fence.binding && canWrite(fence.binding) -> SelectionAvailability.READY
                else -> SelectionAvailability.WAIT
            }
        }, {
            actions.withLock { if (selectionCurrent(fence) && canWrite(fence.binding)) commit() else false }
        })
    private fun currentAccess(binding: String, revision: Long, epoch: Long) =
        accessRevision.get() == revision && network.state.value.epoch == epoch && canWrite(binding)
    private fun unsupported(origin: String, binding: String): Boolean {
        val cached = snapshots.read(origin, binding)
        return updateBinding == binding || cached?.rejectedVersionCode == BuildConfig.VERSION_CODE ||
            cached?.compat?.let { UpdatePolicy.isOutdated(BuildConfig.VERSION_CODE, it.androidMinVersionCode) } == true
    }
    fun canRegisterPush(origin: String, binding: String) = network.state.value.connected && !unsupported(origin, binding)
    fun observePushFailure(origin: String, binding: String, status: Int, updateUrl: String?) {
        if (status in setOf(401, 426)) sessionFailure(origin, binding,
            if (status == 401) QueueOutcome.AUTH_REQUIRED else QueueOutcome.UPDATE_REQUIRED, updateUrl)
    }
    private fun recordUpdateRequired(row: UploadRecord, url: String?) {
        synchronized(sessionStore) {
            if (!matches(row.bindingId)) return
            updateBinding = row.bindingId; writeBinding = null
            accessRevision.incrementAndGet()
            try { snapshots.update(row.origin) { it.copy(rejectedVersionCode = BuildConfig.VERSION_CODE, updateUrl = safeExternalUrl(url.orEmpty()) ?: it.updateUrl) } }
            catch (_: Exception) { currentIssue.value = UploadIssue.STORAGE }
        }
    }

    private fun publishRows() {
        val binding = attached?.third ?: runCatching { sessionStore.origin?.let(sessionStore::readSession)?.bindingId }.getOrNull()
        visibleRows.value = store.rows.value.filter { it.bindingId == binding }
    }
    private fun launchAction(block: suspend () -> Unit) { scope.launch { actions.withLock { safely(block) } } }
    private suspend fun safely(block: suspend () -> Unit) {
        try { block() }
        catch (e: CancellationException) { throw e }
        catch (e: UploadFailure) { currentIssue.value = e.issue }
        catch (_: CredentialUnavailable) { currentIssue.value = UploadIssue.AUTH }
        catch (_: Exception) { currentIssue.value = UploadIssue.SCHEDULING }
    }
    fun attach(origin: String, clientId: Int) = launchAction {
        val credential = sessionStore.readSession(origin) ?: return@launchAction
        if (unsupported(origin, credential.bindingId)) {
            sessionFailure(origin, credential.bindingId, QueueOutcome.UPDATE_REQUIRED); return@launchAction
        }
        val next = Triple(origin, clientId, credential.bindingId)
        if (attached == next) return@launchAction
        attached = next
        blocked.remove(credential.bindingId)
        publishWriteAccess()
        currentIssue.value = null
        publishRows()
        if (store.rows.value.any { it.bindingId == credential.bindingId && eligible(it) }) schedule(credential.bindingId)
    }
    suspend fun select(uris: List<Uri>, expectedPackageId: Int? = null, expectedBindingId: String? = null) = withContext(Dispatchers.IO) {
        safely {
            val binding = attached ?: return@safely
            if (expectedBindingId != null && binding.third != expectedBindingId) return@safely
            selectBound(uris, expectedPackageId, selectionFence(binding.third), wait = false)
        }
    }
    private suspend fun selectBound(uris: List<Uri>, expectedPackageId: Int?, fence: SelectionFence, wait: Boolean) {
        var started = false
        for (uri in uris) {
            val commit: suspend () -> Boolean = commit@{
                if (!started) { currentIssue.value = null; started = true }
                try {
                    val binding = attached?.takeIf { it.third == fence.binding } ?: return@commit false
                    val revision = accessRevision.get(); val epoch = network.state.value.epoch
                    retainAndCommit({ source.retain(uri) }, { selectionCurrent(fence) && currentAccess(binding.third, revision, epoch) }, ::releaseUnused) { document ->
                        if (document.size == 0L) throw UploadFailure(UploadIssue.OVERSIZE)
                        synchronized(sessionStore) {
                            if (!selectionCurrent(fence) || !currentAccess(binding.third, revision, epoch)) false
                            else {
                                store.put(UploadRecord(UUID.randomUUID().toString(), binding.first, binding.third, document.uri, document.filename, document.contentType, binding.second, document.size, expectedPackageId = expectedPackageId))
                                true
                            }
                        }
                    }
                } catch (e: UploadFailure) { currentIssue.value = e.issue; releaseUnused(uri.toString()); true }
            }
            val committed = if (wait) withSelectionAccess(fence, commit) else actions.withLock {
                if (selectionCurrent(fence) && canWrite(fence.binding)) commit() else false
            }
            if (!committed) break
        }
        publishRows()
        if (store.rows.value.any { it.bindingId == fence.binding && eligible(it) }) schedule(fence.binding)
    }
    fun enqueue(uris: List<Uri>) = enqueueBound(uris, null)
    fun enqueue(uris: List<Uri>, expectedPackageId: Int) = enqueueBound(uris, expectedPackageId)
    private fun enqueueBound(uris: List<Uri>, expectedPackageId: Int?) {
        val binding = attached?.third ?: return
        val fence = selectionFence(binding)
        if (!selectionCurrent(fence)) return
        scope.launch { safely {
            // Foreground/review refresh temporarily revokes write access. Never carry
            // a selection across a connectivity epoch or a pairing change.
            selectBound(uris, expectedPackageId, fence, wait = true)
        } }
    }
    private fun schedule(binding: String) {
        if (binding in blocked) return
        if (!UploadNotifications(context).visible()) currentIssue.value = UploadIssue.NOTIFICATIONS
        if (!scheduler.schedule(binding)) schedulingFailed(binding, UploadIssue.SCHEDULING)
    }
    fun schedulingFailed(binding: String, error: UploadIssue) = launchAction {
        if (!matches(binding)) return@launchAction
        currentIssue.value = error
        store.rows.value.filter { it.bindingId == binding && eligible(it) }.forEach { row ->
            store.mutate(row.id) { it.copy(phase = UploadPhase.RETRYABLE, issue = error, retryAtMillis = null) }
        }
    }
    fun matches(binding: String) = binding !in blocked && runCatching { sessionStore.origin?.let(sessionStore::readSession)?.bindingId == binding }.getOrDefault(false)
    fun pending(binding: String) = matches(binding) && store.rows.value.any { it.bindingId == binding && eligible(it) }
    fun pause(id: String) = launchAction {
        val row = bound(id) ?: return@launchAction
        if (row.intent == UploadIntent.PAUSED) return@launchAction
        if (!eligible(row)) return@launchAction
        store.mutate(id) { it.copy(intent = UploadIntent.PAUSED, phase = UploadPhase.PAUSED, retryAtMillis = null) }
        engine.cancel(id)
        if (!pending(row.bindingId)) scheduler.cancel(row.bindingId)
    }
    fun resume(id: String, replacement: Uri? = null) = activate(id, replacement, false)
    fun retry(id: String, replacement: Uri? = null) = activate(id, replacement, true)
    fun resolve(id: String, body: ResolveConflictIn) {
        if (!mutableResolving.compareAndSet(null, id)) return
        scope.launch {
            try { actions.withLock { safely {
                val row = bound(id)?.takeIf { it.phase == UploadPhase.CONFLICT } ?: return@safely
                if (!canWrite(row.bindingId)) return@safely
                currentIssue.value = null
                try { queue.withLock {
                    if (!canWrite(row.bindingId)) return@withLock
                    engine.refresh()
                    if (canWrite(row.bindingId)) engine.resolve(id, body)
                } }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { handleConflictFailure(row, e); throw e }
                publishRows()
                if (pending(row.bindingId)) schedule(row.bindingId)
            } } } finally { mutableResolving.value = null }
        }
    }
    suspend fun preview(id: String, target: ConflictTarget, file: File) {
        if (!network.state.value.connected) throw UploadFailure(UploadIssue.NETWORK)
        val row = bound(id) ?: throw CancellationException("Upload session changed")
        try { engine.preview(id, target.mediaId, file) }
        catch (e: CancellationException) { throw e }
        catch (e: Exception) { handleConflictFailure(row, e); throw e }
    }
    private fun handleConflictFailure(row: UploadRecord, error: Exception) {
        val issue = when (error) {
            is UploadFailure -> error.issue
            is ApiFailure -> when (error.status) { 401 -> UploadIssue.AUTH; 426 -> UploadIssue.UPDATE_REQUIRED; else -> null }
            else -> null
        }
        if (issue in setOf(UploadIssue.AUTH, UploadIssue.UPDATE_REQUIRED)) {
            if (issue == UploadIssue.UPDATE_REQUIRED) recordUpdateRequired(row, (error as? ApiFailure)?.updateUrl)
            sessionFailure(row.origin, row.bindingId, if (issue == UploadIssue.AUTH) QueueOutcome.AUTH_REQUIRED else QueueOutcome.UPDATE_REQUIRED)
            throw UploadFailure(issue!!)
        }
    }
    private fun activate(id: String, replacement: Uri?, retry: Boolean) {
        if (replacement == null) { launchAction { activateNow(id, null, retry) }; return }
        val row = bound(id) ?: return
        val fence = selectionFence(row.bindingId)
        scope.launch { safely { withSelectionAccess(fence) {
            if (bound(id)?.revision != row.revision) true else activateNow(id, replacement, retry, fence)
        } } }
    }
    private suspend fun activateNow(id: String, replacement: Uri?, retry: Boolean, fence: SelectionFence? = null): Boolean {
        val row = bound(id) ?: return true
        val localResume = !retry && replacement == null && row.phase == UploadPhase.PAUSED && row.status?.status in setOf(null, "receiving")
        if (!localResume && !canWrite(row.bindingId)) return false
        if (!retry && !localResume && !(replacement != null && row.phase in setOf(UploadPhase.PAUSED, UploadPhase.NEEDS_FILE))) return true
        if (row.phase in setOf(UploadPhase.QUEUED, UploadPhase.PROCESSING, UploadPhase.FINALIZED, UploadPhase.CONFLICT, UploadPhase.SKIPPED)) return true
        var document: SelectedDocument? = null
        val fresh = retry && (row.phase in setOf(UploadPhase.FAILED, UploadPhase.EXPIRED) || row.status?.status in setOf("failed", "aborted"))
        fun commit(next: SelectedDocument?) = store.mutate(id, row.revision) {
            it.copy(uri = next?.uri ?: it.uri, filename = next?.filename ?: it.filename,
                contentType = next?.contentType ?: it.contentType, size = if (fresh) next?.size else it.size,
                identity = if (fresh) null else it.identity, status = if (fresh) null else it.status,
                intent = UploadIntent.ACTIVE, phase = UploadPhase.WAITING, issue = null, diagnostic = null, failures = if (retry) 0 else it.failures, retryAtMillis = null)
        } != null
        if (replacement != null) {
            val revision = accessRevision.get(); val epoch = network.state.value.epoch
            val current = { (fence == null || selectionCurrent(fence)) && currentAccess(row.bindingId, revision, epoch) }
            val committed = try { retainAndCommit({ source.retain(replacement) }, current, ::releaseUnused,
                verify = { next -> row.identity?.let { identity -> verifyFile({ source.open(next.uri) }, identity) {
                    if (!current()) throw CancellationException("Upload access changed")
                } } }) { next ->
                synchronized(sessionStore) {
                    if (!current()) false else commit(next).also { if (it) document = next }
                }
            } } catch (e: CancellationException) {
                currentCoroutineContext().ensureActive()
                if (!current()) false else throw e
            }
            if (!committed) return false
        } else if (!commit(null)) return true
        if (document != null && document.uri != row.uri) releaseUnused(row.uri)
        currentIssue.value = null
        schedule(row.bindingId)
        return true
    }
    private fun bound(id: String) = store.rows.value.find { it.id == id && matches(it.bindingId) }
    fun dismiss(id: String) = launchAction {
        val row = bound(id) ?: return@launchAction
        if (!canWrite(row.bindingId)) return@launchAction
        if (eligible(row)) return@launchAction
        store.remove(id)
        engine.cancel(id)
        releaseUnused(row.uri)
    }
    private fun releaseUnused(uri: String) { if (store.rows.value.none { it.uri == uri }) runCatching { source.release(uri) } }
    fun stopSession() {
        val binding = attached?.third ?: runCatching { sessionStore.origin?.let(sessionStore::readSession)?.bindingId }.getOrNull() ?: return
        stopBinding(binding)
    }
    private fun stopBinding(binding: String) {
        accessRevision.incrementAndGet()
        if (writeBinding == binding) writeBinding = null
        blocked.add(binding)
        if (attached?.third == binding) attached = null
        store.rows.value.filter { it.bindingId == binding }.forEach { engine.cancel(it.id) }
        launchAction {
            store.rows.value.filter { it.bindingId == binding && eligible(it) }.forEach { row ->
                store.mutate(row.id) { it.copy(intent = UploadIntent.PAUSED, phase = UploadPhase.PAUSED, retryAtMillis = null) }
            }
            scheduler.cancel(binding)
            publishRows()
        }
    }
    suspend fun runQueue(onProgress: (UploadRecord) -> Unit): QueueOutcome = queue.withLock {
        val origin = sessionStore.origin ?: return@withLock QueueOutcome.IDLE
        val credential = sessionStore.readSession(origin) ?: return@withLock QueueOutcome.IDLE
        if (!matches(credential.bindingId)) return@withLock QueueOutcome.IDLE
        if (unsupported(origin, credential.bindingId)) {
            sessionFailure(origin, credential.bindingId, QueueOutcome.UPDATE_REQUIRED)
            return@withLock QueueOutcome.UPDATE_REQUIRED
        }
        try {
            val result = engine.run(onProgress)
            if (result == QueueOutcome.AUTH_REQUIRED || result == QueueOutcome.UPDATE_REQUIRED) sessionFailure(origin, credential.bindingId, result)
            result
        } catch (e: UploadFailure) {
            currentIssue.value = e.issue
            QueueOutcome.IDLE
        } catch (_: CredentialUnavailable) {
            sessionFailure(origin, credential.bindingId, QueueOutcome.AUTH_REQUIRED)
            QueueOutcome.AUTH_REQUIRED
        }
    }
    private fun sessionFailure(origin: String, binding: String, outcome: QueueOutcome, updateUrl: String? = null) {
        synchronized(sessionStore) {
            if (!matches(binding)) return
            if (outcome == QueueOutcome.UPDATE_REQUIRED) {
                updateBinding = binding
                runCatching { snapshots.update(origin) { it.copy(rejectedVersionCode = BuildConfig.VERSION_CODE,
                    updateUrl = safeExternalUrl(updateUrl.orEmpty()) ?: it.updateUrl) } }
            }
            stopBinding(binding)
            if (outcome == QueueOutcome.AUTH_REQUIRED) {
                if (!sessionStore.clearTokenIfBinding(origin, binding)) return
                runCatching { snapshots.update(origin) { it.copy(data = null) } }
            }
            failureBinding = binding
            currentIssue.value = if (outcome == QueueOutcome.AUTH_REQUIRED) UploadIssue.AUTH else UploadIssue.UPDATE_REQUIRED
        }
    }
    suspend fun refresh() {
        if (!network.state.value.connected) return
        safely {
            val origin = sessionStore.origin
            val binding = origin?.let(sessionStore::readSession)?.bindingId
            try { engine.refresh() }
            catch (e: UploadFailure) {
                if (origin != null && binding != null && e.issue in setOf(UploadIssue.AUTH, UploadIssue.UPDATE_REQUIRED)) sessionFailure(origin, binding, if (e.issue == UploadIssue.AUTH) QueueOutcome.AUTH_REQUIRED else QueueOutcome.UPDATE_REQUIRED)
                else throw e
            }
            if (binding != null && pending(binding)) schedule(binding)
        }
    }
    companion object {
        @android.annotation.SuppressLint("StaticFieldLeak") // Only applicationContext is retained.
        @Volatile private var instance: UploadRuntime? = null
        fun get(context: Context): UploadRuntime = instance ?: synchronized(this) {
            instance ?: UploadRuntime(context.applicationContext).also { instance = it }
        }
    }
}
