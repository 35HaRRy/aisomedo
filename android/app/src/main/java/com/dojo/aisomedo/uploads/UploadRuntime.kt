package com.dojo.aisomedo.uploads

import android.content.Context
import android.net.Uri
import com.dojo.aisomedo.BuildConfig
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.OkHttpClient
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.io.File

class UploadRuntime private constructor(private val context: Context) {
    val sessionStore = SessionStore(context.noBackupFilesDir.resolve("session")) { androidKeystoreKey() }
    private val store = UploadStore(context.noBackupFilesDir.resolve("uploads"))
    private val source = UploadSource(context.contentResolver)
    private val scheduler = UploadScheduler(context)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val actions = Mutex()
    private val queue = Mutex()
    private val blocked = ConcurrentHashMap.newKeySet<String>()
    @Volatile private var attached: Triple<String, Int, String>? = null
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
    }, { row, credential -> DojoApi(row.origin, credential.token, BuildConfig.VERSION_CODE, http) }, System::currentTimeMillis)
    init {
        // Remove only this feature's abandoned private previews after process death.
        context.cacheDir.resolve("conflict-previews").listFiles()?.filter { it.isFile }?.forEach { it.delete() }
        scope.launch { store.rows.collect { publishRows() } }
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
        val next = Triple(origin, clientId, credential.bindingId)
        if (attached == next) return@launchAction
        attached = next
        blocked.remove(credential.bindingId)
        currentIssue.value = null
        publishRows()
        if (store.rows.value.any { it.bindingId == credential.bindingId && eligible(it) }) schedule(credential.bindingId)
    }
    suspend fun select(uris: List<Uri>) = withContext(Dispatchers.IO) {
        actions.withLock { safely {
            val binding = attached ?: return@safely
            if (sessionStore.readSession(binding.first)?.bindingId != binding.third || binding.third in blocked) return@safely
            currentIssue.value = null
            for (uri in uris) {
                try {
                    val document = source.retain(uri)
                    if (document.size == 0L) throw UploadFailure(UploadIssue.OVERSIZE)
                    store.put(UploadRecord(UUID.randomUUID().toString(), binding.first, binding.third, document.uri, document.filename, document.contentType, binding.second, document.size))
                } catch (e: UploadFailure) { currentIssue.value = e.issue; releaseUnused(uri.toString()) }
            }
            publishRows()
            if (store.rows.value.any { it.bindingId == binding.third && eligible(it) }) schedule(binding.third)
        } }
    }
    fun enqueue(uris: List<Uri>) { scope.launch { select(uris) } }
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
                currentIssue.value = null
                try { queue.withLock { engine.resolve(id, body) } }
                catch (e: CancellationException) { throw e }
                catch (e: Exception) { handleConflictFailure(row, e); throw e }
                publishRows()
                if (pending(row.bindingId)) schedule(row.bindingId)
            } } } finally { mutableResolving.value = null }
        }
    }
    suspend fun preview(id: String, target: ConflictTarget, file: File) {
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
            sessionFailure(row.origin, row.bindingId, if (issue == UploadIssue.AUTH) QueueOutcome.AUTH_REQUIRED else QueueOutcome.UPDATE_REQUIRED)
            throw UploadFailure(issue!!)
        }
    }
    private fun activate(id: String, replacement: Uri?, retry: Boolean) = launchAction {
        val row = bound(id) ?: return@launchAction
        if (row.phase in setOf(UploadPhase.QUEUED, UploadPhase.PROCESSING, UploadPhase.FINALIZED, UploadPhase.CONFLICT, UploadPhase.SKIPPED)) return@launchAction
        var document: SelectedDocument? = null
        if (replacement != null) {
            document = source.retain(replacement)
            try { row.identity?.let { identity -> verifyFile({ source.open(document.uri) }, identity) {} } }
            catch (e: Exception) { releaseUnused(document.uri); throw e }
        }
        val fresh = retry && (row.phase in setOf(UploadPhase.FAILED, UploadPhase.EXPIRED) || row.status?.status in setOf("failed", "aborted"))
        store.mutate(id, row.revision) { it.copy(uri = document?.uri ?: it.uri, filename = document?.filename ?: it.filename,
            contentType = document?.contentType ?: it.contentType, size = if (fresh) document?.size else it.size,
            identity = if (fresh) null else it.identity, status = if (fresh) null else it.status,
            intent = UploadIntent.ACTIVE, phase = UploadPhase.WAITING, issue = null, diagnostic = null, failures = 0, retryAtMillis = null) }
        if (document != null && document.uri != row.uri) releaseUnused(row.uri)
        currentIssue.value = null
        schedule(row.bindingId)
    }
    private fun bound(id: String) = store.rows.value.find { it.id == id && matches(it.bindingId) }
    fun dismiss(id: String) = launchAction {
        val row = bound(id) ?: return@launchAction
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
    private fun sessionFailure(origin: String, binding: String, outcome: QueueOutcome) {
        synchronized(sessionStore) {
            if (!matches(binding)) return
            stopBinding(binding)
            if (outcome == QueueOutcome.AUTH_REQUIRED && !sessionStore.clearTokenIfBinding(origin, binding)) return
            failureBinding = binding
            currentIssue.value = if (outcome == QueueOutcome.AUTH_REQUIRED) UploadIssue.AUTH else UploadIssue.UPDATE_REQUIRED
        }
    }
    suspend fun refresh() {
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
