package com.dojo.aisomedo.uploads

import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.SessionCredential
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.SerializationException
import java.io.InputStream
import java.io.File
import java.util.concurrent.ConcurrentHashMap

internal fun eligible(row: UploadRecord) = row.intent == UploadIntent.ACTIVE && row.failures < 5 &&
    (row.phase in setOf(UploadPhase.WAITING, UploadPhase.PREPARING, UploadPhase.UPLOADING) ||
        (row.phase == UploadPhase.RETRYABLE && row.retryAtMillis != null))

class UploadEngine(
    private val store: UploadStore,
    private val open: (String) -> InputStream,
    private val session: (UploadRecord) -> SessionCredential?,
    private val api: (UploadRecord, SessionCredential) -> DojoApi,
    private val now: () -> Long,
) {
    private val guard = Mutex()
    private val jobs = ConcurrentHashMap<String, Job>()
    fun cancel(id: String) { jobs[id]?.cancel() }

    suspend fun resolve(id: String, body: ResolveConflictIn) = withContext(Dispatchers.IO) {
        guard.withLock {
            val row = store.rows.value.find { it.id == id && it.phase == UploadPhase.CONFLICT } ?: return@withLock
            if (row.pendingDecision != null) { Attempt(row) {}.refresh(); return@withLock }
            if (body.decision !in conflictDecisions || (body.decision == "keep_selected" &&
                (!body.confirmedOverwrite || conflictTargets(row.status).none { it.mediaId == body.targetMediaId }))) {
                throw UploadFailure(UploadIssue.INVALID_RESPONSE)
            }
            val attempt = Attempt(row) {}
            attempt.resolve(body)
        }
    }
    suspend fun preview(id: String, targetId: String, file: File) = withContext(Dispatchers.IO) {
        val row = store.rows.value.find { it.id == id && it.phase == UploadPhase.CONFLICT }
            ?: throw CancellationException("Conflict changed")
        val target = conflictTargets(row.status).find { it.mediaId == targetId } ?: throw UploadFailure(UploadIssue.INVALID_RESPONSE)
        try { Attempt(row) {}.preview(target, file) }
        catch (e: Exception) { file.delete(); throw e }
    }

    suspend fun run(onProgress: (UploadRecord) -> Unit): QueueOutcome = withContext(Dispatchers.IO) {
        if (!guard.tryLock()) return@withContext QueueOutcome.IDLE
        try {
            for (id in store.rows.value.map { it.id }) {
                currentCoroutineContext().ensureActive()
                val row = store.rows.value.find { it.id == id } ?: continue
                if (!eligible(row) || session(row)?.bindingId != row.bindingId || (row.retryAtMillis ?: 0) > now()) continue
                val outcome = supervisorScope {
                    val child = async(start = CoroutineStart.LAZY) { Attempt(row, onProgress).run() }
                    jobs[id] = child
                    try { child.await() }
                    catch (e: CancellationException) { currentCoroutineContext().ensureActive(); QueueOutcome.IDLE }
                    finally { jobs.remove(id, child) }
                }
                if (outcome == QueueOutcome.AUTH_REQUIRED || outcome == QueueOutcome.UPDATE_REQUIRED) return@withContext outcome
            }
            if (store.rows.value.any { eligible(it) && session(it)?.bindingId == it.bindingId }) QueueOutcome.RETRY else QueueOutcome.IDLE
        } finally { guard.unlock() }
    }

    suspend fun refresh() = withContext(Dispatchers.IO) {
        if (!guard.tryLock()) return@withContext
        try {
            for (row in store.rows.value.filter { it.pendingDecision != null || it.phase in setOf(UploadPhase.QUEUED, UploadPhase.PROCESSING, UploadPhase.CONFLICT) }) {
                val attempt = Attempt(row) {}
                try { attempt.refresh() }
                catch (e: CancellationException) { currentCoroutineContext().ensureActive() }
            }
        } finally { guard.unlock() }
    }

    private inner class Attempt(private var row: UploadRecord, private val onProgress: (UploadRecord) -> Unit) {
        private var operation = "status"
        private lateinit var credential: SessionCredential
        private lateinit var remote: DojoApi
        private fun fence(active: Boolean = true) {
            val current = store.rows.value.find { it.id == row.id }
            if (current?.revision != row.revision || (active && current.intent != UploadIntent.ACTIVE) || session(row)?.bindingId != row.bindingId) throw CancellationException("Upload action changed")
        }
        private fun save(active: Boolean = true, change: (UploadRecord) -> UploadRecord) {
            fence(active)
            row = store.mutate(row.id, row.revision, change) ?: throw CancellationException("Upload action changed")
            onProgress(row)
        }
        private suspend fun authenticate() {
            credential = session(row)?.takeIf { it.bindingId == row.bindingId } ?: throw CancellationException("Upload session changed")
            remote = api(row, credential)
            fence(false)
            val me = try { remote.me() } catch (e: ApiFailure) { fence(false); throw e }
            fence(false)
            if (me.id != row.clientId || me.kind != "device" || me.revokedAt != null) throw UploadFailure(UploadIssue.AUTH)
        }
        private fun diagnostic(value: String?): String? = value?.replace(credential.token, "[redacted]")?.filter { !it.isISOControl() }?.take(1024)
        private suspend fun accept(status: UploadOut, active: Boolean = true) {
            validateStatus(status, row.identity!!.size, row.status?.uploadId)
            fence(active)
            val skipped = status.status == "aborted" && remote.uploadWasSkipped(status.uploadId)
            fence(active)
            val progress = status.receivedBytes > (row.status?.receivedBytes ?: 0)
            val phase = when (status.status) {
                "receiving" -> UploadPhase.UPLOADING
                "queued" -> UploadPhase.QUEUED
                "processing" -> UploadPhase.PROCESSING
                "finalized" -> UploadPhase.FINALIZED
                "conflict" -> UploadPhase.CONFLICT
                "aborted" -> if (skipped) UploadPhase.SKIPPED else UploadPhase.EXPIRED
                else -> UploadPhase.FAILED
            }
            save(active) { it.copy(status = status, phase = if (status.status == "receiving" && it.intent == UploadIntent.PAUSED) UploadPhase.PAUSED else phase,
                pendingDecision = it.pendingDecision.takeIf { status.status == "conflict" }, diagnostic = diagnostic(status.errorReason),
                issue = when (phase) { UploadPhase.CONFLICT -> UploadIssue.CONFLICT; UploadPhase.EXPIRED -> UploadIssue.EXPIRED; UploadPhase.FAILED -> UploadIssue.SERVER; else -> null },
                failures = if (progress) 0 else it.failures, retryAtMillis = if (progress) null else it.retryAtMillis) }
        }
        suspend fun refresh() {
            try {
                authenticate()
                fence(false)
                accept(remote.uploadStatus(row.status!!.uploadId), false)
            } catch (e: ApiFailure) {
                fence(false)
                if (e.status == 401) throw UploadFailure(UploadIssue.AUTH)
                if (e.status == 426) throw UploadFailure(UploadIssue.UPDATE_REQUIRED)
                if (e.status == 404) save(false) { it.copy(phase = UploadPhase.EXPIRED, issue = UploadIssue.EXPIRED, pendingDecision = null) }
            }
        }
        suspend fun preview(target: ConflictTarget, file: File) {
            authenticate()
            fence(false)
            // ponytail: bounded private cache (10 MiB image / 512 MiB video); range streaming if larger previews are needed.
            remote.conflictPreview(row.status!!.uploadId, target.mediaId, file,
                if (target.contentType == "video/mp4") 512L * 1024 * 1024 else 10L * 1024 * 1024)
            fence(false)
        }
        suspend fun resolve(body: ResolveConflictIn) {
            authenticate()
            fence(false)
            // Collision target IDs encode server Unicode casefold; local lowercasing does not.
            if (body.applyToAll) {
                for (candidate in store.rows.value.filter { it.bindingId == row.bindingId && it.phase == UploadPhase.CONFLICT && conflictTargets(it.status).isEmpty() }) {
                    Attempt(candidate) {}.refresh()
                    if (candidate.id == row.id) row = store.rows.value.find { it.id == row.id } ?: throw CancellationException("Upload removed")
                }
                fence(false)
                if (row.phase != UploadPhase.CONFLICT) return
                if (store.rows.value.any { it.bindingId == row.bindingId && it.phase == UploadPhase.CONFLICT && conflictTargets(it.status).isEmpty() })
                    throw UploadFailure(UploadIssue.INVALID_RESPONSE)
            }
            val ids = conflictTargets(row.status).map { it.mediaId }.toSet()
            if (body.applyToAll && ids.isEmpty()) throw UploadFailure(UploadIssue.INVALID_RESPONSE)
            val candidates = store.rows.value.filter { it.id == row.id || (body.applyToAll && it.bindingId == row.bindingId &&
                it.phase == UploadPhase.CONFLICT && it.status?.packageId == row.status?.packageId && conflictTargets(it.status).any { target -> target.mediaId in ids }) }
            for (candidate in candidates) {
                fence(false)
                val saved = store.mutate(candidate.id, candidate.revision) { it.copy(pendingDecision = body.decision, issue = null, diagnostic = null) }
                    ?: throw CancellationException("Upload changed")
                if (saved.id == row.id) row = saved
            }
            var failure: Exception? = null
            try {
                // Bulk response may belong to a sibling. GET each ID rather than accepting it.
                remote.resolveUpload(row.status!!.uploadId, body)
                fence(false)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                fence(false)
                failure = e
                if (e is ApiFailure && e.status in 400..499 && e.status !in setOf(408, 429)) {
                    for (candidate in candidates) {
                        val current = store.rows.value.find { it.id == candidate.id } ?: continue
                        val saved = store.mutate(current.id, current.revision) { it.copy(pendingDecision = null) }
                        if (saved?.id == row.id) row = saved
                    }
                }
            }
            for (candidate in candidates) {
                fence(false)
                val current = store.rows.value.find { it.id == candidate.id } ?: continue
                try {
                    val reconcile = Attempt(current) {}
                    reconcile.refresh()
                } catch (e: CancellationException) { throw e }
                catch (e: UploadFailure) { throw e }
                catch (e: Exception) { failure = e }
                if (candidate.id == row.id) row = store.rows.value.find { it.id == row.id } ?: throw CancellationException("Upload removed")
            }
            if (failure != null && row.phase == UploadPhase.CONFLICT) {
                val issue = when ((failure as? ApiFailure)?.status) {
                    401 -> UploadIssue.AUTH; 426 -> UploadIssue.UPDATE_REQUIRED; 0 -> UploadIssue.NETWORK
                    else -> UploadIssue.SERVER
                }
                save(false) { it.copy(issue = issue, diagnostic = diagnostic((failure as? ApiFailure)?.detail)) }
                if (issue in setOf(UploadIssue.AUTH, UploadIssue.UPDATE_REQUIRED)) throw UploadFailure(issue)
            }
        }
        suspend fun run(): QueueOutcome {
            try {
                authenticate()
                fence()
                if (row.status == null) {
                    operation = "limits"
                    val limits = remote.uploadLimits()
                    if (limits.maxFileBytes <= 0 || limits.maxPackageBytes <= 0 || limits.activePackageId == null || limits.activePackageId < 0) throw UploadFailure(UploadIssue.INVALID_RESPONSE)
                    save { it.copy(phase = UploadPhase.PREPARING, issue = null) }
                    val identity = prepareFile({ open(row.uri) }, row.size, limits.maxFileBytes) { fence() }
                    save { it.copy(identity = identity, size = identity.size) }
                    fence()
                    operation = "init"
                    accept(remote.startUpload(UploadInitIn(row.contentType, identity.size, limits.activePackageId, row.filename)))
                } else {
                    operation = "status"
                    accept(remote.uploadStatus(row.status!!.uploadId))
                }
                if (row.status!!.status != "receiving") return QueueOutcome.IDLE
                val identity = row.identity!!
                if (row.status!!.receivedBytes < identity.size) {
                    save { it.copy(phase = UploadPhase.PREPARING) }
                    verifyFile({ open(row.uri) }, identity) { fence() }
                    save { it.copy(phase = UploadPhase.UPLOADING) }
                    operation = "range"
                    val length = scanChunks({ open(row.uri) }, identity.size) { offset, bytes, count ->
                        fence()
                        if (sha256(bytes, count) != identity.chunkHashes[(offset / CHUNK_BYTES).toInt()]) throw UploadFailure(UploadIssue.WRONG_FILE)
                        val end = offset + count
                        if (!row.status!!.receivedRanges.any { it[0] <= offset && it[1] >= end }) {
                            val status = remote.uploadRange(row.status!!.uploadId, offset, identity.chunkHashes[(offset / CHUNK_BYTES).toInt()], bytes.copyOf(count))
                            accept(status)
                            if (status.status != "receiving") throw CancellationException("Upload no longer receiving")
                        }
                    }
                    if (length != identity.size) throw UploadFailure(UploadIssue.WRONG_FILE)
                }
                fence()
                if (row.status!!.receivedBytes != identity.size) throw UploadFailure(UploadIssue.INVALID_RESPONSE)
                operation = "complete"
                accept(remote.completeUpload(row.status!!.uploadId))
                if (row.status!!.status == "receiving") throw UploadFailure(UploadIssue.INVALID_RESPONSE)
                return QueueOutcome.IDLE
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                fence()
                if (e is UploadFailure && e.issue == UploadIssue.STORAGE) throw e
                val transient = e is ApiFailure && (e.status == 0 || e.status == 408 || e.status == 429 || e.status >= 500)
                if (e is ApiFailure && row.status != null && operation in setOf("range", "complete") && (transient || e.status == 409)) {
                    try {
                        fence()
                        accept(remote.uploadStatus(row.status!!.uploadId))
                        if (row.status!!.status != "receiving") return QueueOutcome.IDLE
                    } catch (cancel: CancellationException) { throw cancel }
                    catch (reconcile: Exception) {
                        if (reconcile is UploadFailure || (reconcile is ApiFailure && reconcile.status in setOf(401, 426, 404))) return fail(reconcile, false)
                    }
                }
                return fail(e, transient && operation != "init")
            }
        }
        private fun fail(error: Exception, automatic: Boolean): QueueOutcome {
            val issue = when (error) {
                is UploadFailure -> error.issue
                is SerializationException -> UploadIssue.INVALID_RESPONSE
                is ApiFailure -> when (error.status) {
                    401 -> UploadIssue.AUTH; 426 -> UploadIssue.UPDATE_REQUIRED; 404 -> UploadIssue.EXPIRED
                    413 -> UploadIssue.OVERSIZE
                    409 -> if (error.detail?.contains("changed", true) == true) UploadIssue.PACKAGE_CHANGED else UploadIssue.CAPACITY
                    400 -> if (operation == "range") UploadIssue.CHECKSUM else UploadIssue.SERVER
                    else -> if (error.status == 0) UploadIssue.NETWORK else UploadIssue.SERVER
                }
                else -> UploadIssue.FILE_ACCESS
            }
            val failures = if (automatic) minOf(5, row.failures + 1) else row.failures
            val phase = when (issue) {
                UploadIssue.FILE_ACCESS, UploadIssue.WRONG_FILE -> UploadPhase.NEEDS_FILE
                UploadIssue.EXPIRED -> UploadPhase.EXPIRED
                UploadIssue.NETWORK, UploadIssue.AUTH, UploadIssue.UPDATE_REQUIRED -> UploadPhase.RETRYABLE
                else -> if (automatic || (error is ApiFailure && (error.status == 408 || error.status == 429 || error.status >= 500))) UploadPhase.RETRYABLE else UploadPhase.FAILED
            }
            save { it.copy(phase = phase, issue = issue, diagnostic = diagnostic((error as? ApiFailure)?.detail), failures = failures,
                retryAtMillis = if (automatic && failures < 5) now() + minOf(18_000_000L, 30_000L shl (failures - 1)) else null) }
            return when (issue) { UploadIssue.AUTH -> QueueOutcome.AUTH_REQUIRED; UploadIssue.UPDATE_REQUIRED -> QueueOutcome.UPDATE_REQUIRED; else -> QueueOutcome.IDLE }
        }
    }
}
