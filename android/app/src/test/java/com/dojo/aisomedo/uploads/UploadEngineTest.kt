package com.dojo.aisomedo.uploads

import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.SessionCredential
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit

class UploadEngineTest {
    private class Fixture(val content: ByteArray = ByteArray(CHUNK_BYTES + 1) { 7 }) : AutoCloseable {
        val directory = Files.createTempDirectory("upload-engine").toFile()
        val store = UploadStore(directory)
        val server = MockWebServer()
        val puts = CopyOnWriteArrayList<Long>()
        var initializations = 0
        var completions = 0
        var confirmed = 0L
        var status = "receiving"
        var error = 0
        var initError = 0
        var max = 2L * CHUNK_BYTES
        var losePut = false
        var loseComplete = false
        var responseDelay = false
        var invalid = false
        var resolveError = 0
        var statusError = 0
        var hideAudit = false
        var loseResolve = false
        var delayResolve = false
        val resolutions = CopyOnWriteArrayList<String>()
        val resolved = mutableMapOf<String, String>()
        val targets = buildJsonObject {
            put("media_id", "target"); put("filename", "Straße.jpg"); put("size_bytes", 1)
            put("uploaded_at", "2026-10-09T10:00:00Z")
            put("processed", buildJsonObject { put("content_type", "image/jpeg") })
        }
        var clock = 0L
        var credential: SessionCredential? = SessionCredential("a".repeat(64), "TEST-ONLY")
        val putStarted = CompletableDeferred<Unit>()
        val engine: UploadEngine
        init {
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    val path = request.requestUrl!!.encodedPath
                    if (path == "/api/pairing/me") return MockResponse().setBody("""{"id":1,"kind":"device","name":"test","created_at":"now","created_by":"test","last_seen_at":null,"revoked_at":null}""")
                    if (path == "/api/activity") {
                        val events = resolved.filterValues { it == "aborted" }.keys.mapIndexed { index, id -> buildJsonObject {
                            put("id", index + 1); put("action", "conflict.resolved"); put("occurred_at", "2026-10-09T10:00:00Z"); put("actor", "system")
                            put("details", buildJsonObject { put("upload_id", id); put("decision", "keep_target") })
                        } }.toMutableList()
                        if (status == "aborted" && resolved["saved"] == null) events.add(buildJsonObject {
                            put("action", "upload.expired"); put("details", buildJsonObject { put("upload_id", "saved") })
                        })
                        return MockResponse().setBody(buildJsonObject { put("events", JsonArray(if (hideAudit) emptyList() else events)); put("next_cursor", JsonNull) }.toString())
                    }
                    if (error != 0) return MockResponse().setResponseCode(error)
                    if (path.endsWith("resolve")) {
                        val body = request.body.readUtf8()
                        resolutions.add(body)
                        putStarted.complete(Unit)
                        if (resolveError != 0) return MockResponse().setResponseCode(resolveError)
                        val decision = Json.parseToJsonElement(body).jsonObject["decision"]!!.jsonPrimitive.content
                        resolved["saved"] = if (decision == "keep_target") "aborted" else "receiving"
                        if (Json.parseToJsonElement(body).jsonObject["apply_to_all"]?.jsonPrimitive?.booleanOrNull == true) resolved["second"] = resolved["saved"]!!
                        if (loseResolve) { loseResolve = false; return MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST) }
                        // Bulk response intentionally belongs to a different upload.
                        return MockResponse().setBody(Json.encodeToString(UploadOut.serializer(), UploadOut(declaredSizeBytes = content.size.toLong(), receivedBytes = 0,
                            receivedRanges = emptyList(), status = resolved["saved"]!!, uploadId = "second"))).apply {
                            if (delayResolve) setBodyDelay(2, TimeUnit.SECONDS)
                        }
                    }
                    if (request.method == "GET" && path.startsWith("/api/media/uploads/") && statusError != 0) return MockResponse().setResponseCode(statusError)
                    if (path.endsWith("upload-limits")) return MockResponse().setBody("""{"max_file_bytes":$max,"max_package_bytes":$max,"active_package_id":0}""")
                    if (request.method == "POST" && path.endsWith("uploads")) {
                        initializations++
                        if (initError != 0) return MockResponse().setResponseCode(initError).setBody("""{"detail":"package limit exceeded"}""")
                    }
                    if (request.method == "PUT") {
                        val offset = request.requestUrl!!.queryParameter("offset")!!.toLong()
                        puts.add(offset)
                        confirmed = offset + request.body.size
                        putStarted.complete(Unit)
                        if (losePut) { losePut = false; return MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST) }
                    }
                    if (path.endsWith("complete")) {
                        completions++
                        status = "queued"
                        if (loseComplete) { loseComplete = false; return MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST) }
                    }
                    val uploadId = path.removePrefix("/api/media/uploads/").takeIf { !it.contains('/') && it != path } ?: "saved"
                    val state = resolved[uploadId] ?: status
                    val out = UploadOut(declaredSizeBytes = content.size.toLong(), receivedBytes = confirmed,
                        receivedRanges = if (confirmed > 0) listOf(listOf(0, confirmed)) else emptyList(), status = state,
                        conflicts = if (state == "conflict") listOf(targets) else emptyList(), packageId = 1, uploadId = if (invalid) "wrong" else uploadId)
                    return MockResponse().setBody(Json.encodeToString(UploadOut.serializer(), out)).apply {
                        if (responseDelay && request.method == "PUT") setBodyDelay(2, TimeUnit.SECONDS)
                    }
                }
            }
            server.start()
            engine = UploadEngine(store, { content.inputStream() }, { credential }, { row, auth -> DojoApi(row.origin, auth.token, 5, OkHttpClient()) }, { clock })
        }
        suspend fun add(known: Boolean = true): UploadRecord {
            val identity = if (known) prepareFile({ content.inputStream() }, null, Long.MAX_VALUE) {} else null
            val row = UploadRecord(UUID.randomUUID().toString(), server.url("/").toString().trimEnd('/'), "a".repeat(64), "content://test/file", "file.jpg", "image/jpeg", 1,
                content.size.toLong().takeIf { it > 0 }, identity,
                if (known) UploadOut(declaredSizeBytes = content.size.toLong(), receivedBytes = 0, receivedRanges = emptyList(), status = "receiving", uploadId = "saved") else null)
            store.put(row)
            return row
        }
        override fun close() { server.close(); directory.deleteRecursively() }
    }
    @Test fun resumesKnownIdAfterLostPutResponse() = runBlocking {
        Fixture().use { f ->
            f.add(); f.losePut = true
            f.engine.run {}
            f.clock = 3_600_000
            f.engine.run {}
            assertEquals(listOf(0L, 2097152L), f.puts)
            assertEquals(0, f.initializations)
            assertEquals("saved", f.store.rows.value.single().status!!.uploadId)
            assertEquals(UploadPhase.QUEUED, f.store.rows.value.single().phase)
        }
    }
    @Test fun conflictRefreshRecoversDecisionMadeOnAnotherClient() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.add()
            f.store.mutate(row.id) { it.copy(phase = UploadPhase.CONFLICT, status = it.status!!.copy(status = "conflict")) }
            f.engine.refresh()
            assertEquals("receiving", f.store.rows.value.single().status!!.status)
            assertTrue(eligible(f.store.rows.value.single()))
        }
    }
    private suspend fun Fixture.conflict(uploadId: String = "saved", filename: String = "Straße.jpg", targetId: String = "target"): UploadRecord {
        val row = add()
        status = "conflict"
        return store.mutate(row.id) { it.copy(filename = filename, phase = UploadPhase.CONFLICT,
            status = it.status!!.copy(status = "conflict", uploadId = uploadId, packageId = 1,
                conflicts = listOf(targets + ("media_id" to JsonPrimitive(targetId))))) }!!
    }
    @Test fun bulkResolutionReconcilesByIdAndUsesServerUnicodeTargets() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val first = f.conflict()
            val second = f.conflict("second", "STRASSE.jpg")
            val unrelated = f.conflict("unrelated", "other.jpg", "other-target")
            f.engine.resolve(first.id, ResolveConflictIn(decision = "keep_both", applyToAll = true))
            assertTrue(eligible(f.store.rows.value.find { it.id == first.id }!!))
            assertTrue(eligible(f.store.rows.value.find { it.id == second.id }!!))
            assertEquals(UploadPhase.CONFLICT, f.store.rows.value.find { it.id == unrelated.id }!!.phase)
            assertEquals(1, f.resolutions.size)
            assertEquals("saved", f.store.rows.value.find { it.id == first.id }!!.status!!.uploadId)
        }
    }
    @Test fun lostKeepTargetResponseBecomesSkippedWithoutReplay() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val first = f.conflict(); f.conflict("second", "STRASSE.jpg")
            f.loseResolve = true
            f.engine.resolve(first.id, ResolveConflictIn(decision = "keep_target", applyToAll = true))
            assertTrue(f.store.rows.value.all { it.phase == UploadPhase.SKIPPED && it.issue == null })
            f.engine.run {}; f.engine.refresh()
            assertEquals(1, f.resolutions.size)
            assertTrue(f.puts.isEmpty())
            assertTrue(UploadStore(f.directory).rows.value.all { it.phase == UploadPhase.SKIPPED })
        }
    }
    @Test fun overwriteRequiresConfirmationAndCurrentValidTarget() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            for (body in listOf(ResolveConflictIn(decision = "keep_selected", targetMediaId = "target"),
                ResolveConflictIn(decision = "keep_selected", confirmedOverwrite = true, targetMediaId = "wrong"),
                ResolveConflictIn(decision = "unknown"))) {
                assertTrue(runCatching { f.engine.resolve(row.id, body) }.isFailure)
            }
            assertTrue(f.resolutions.isEmpty())
            f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_selected", confirmedOverwrite = true, targetMediaId = "target"))
            val body = Json.parseToJsonElement(f.resolutions.single()).jsonObject
            assertEquals("target", body["target_media_id"]!!.jsonPrimitive.content)
            assertTrue(body["confirmed_overwrite"]!!.jsonPrimitive.boolean)
            assertTrue(eligible(f.store.rows.value.single()))
        }
    }
    @Test fun definitiveRejectionCannotTurnLaterAbortIntoSkip() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict(); f.resolveError = 409
            f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_target"))
            assertEquals(UploadPhase.CONFLICT, f.store.rows.value.single().phase)
            assertNull(f.store.rows.value.single().pendingDecision)
            f.status = "aborted"; f.engine.refresh()
            assertEquals(UploadPhase.EXPIRED, f.store.rows.value.single().phase)
        }
    }
    @Test fun timeoutOrRateLimitDoesNotReleaseUnknownOutcomeProtection() = runBlocking {
        for (status in listOf(408, 429)) Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict(); f.resolveError = status
            f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_target"))
            assertEquals("keep_target", f.store.rows.value.single().pendingDecision)
            f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_both"))
            assertEquals(1, f.resolutions.size)
        }
    }
    @Test fun pendingKeepTargetSurvivesRestartAndRefreshNeverReplaysPost() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            f.store.mutate(row.id) { it.copy(pendingDecision = "keep_target") }
            f.status = "aborted"
            f.resolved["saved"] = "aborted"
            val restarted = UploadStore(f.directory)
            val engine = UploadEngine(restarted, { f.content.inputStream() }, { f.credential },
                { r, c -> DojoApi(r.origin, c.token, 5, OkHttpClient()) }, { 0 })
            engine.refresh()
            assertEquals(UploadPhase.SKIPPED, restarted.rows.value.single().phase)
            assertTrue(f.resolutions.isEmpty())
        }
    }
    @Test fun bulkResolutionRecoversMissingPrimaryTargetMetadata() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            f.store.mutate(row.id) { it.copy(status = it.status!!.copy(conflicts = emptyList())) }
            f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_target", applyToAll = true))
            assertEquals(UploadPhase.SKIPPED, f.store.rows.value.single().phase)
            assertEquals(1, f.resolutions.size)
        }
    }
    @Test fun ambiguousDecisionBlocksReplayUntilStatusIsKnown() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            f.loseResolve = true; f.statusError = 503
            f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_target"))
            assertEquals("keep_target", f.store.rows.value.single().pendingDecision)
            assertEquals(UploadPhase.CONFLICT, f.store.rows.value.single().phase)
            assertNotNull(f.store.rows.value.single().issue)
            runCatching { f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_selected", targetMediaId = "target", confirmedOverwrite = true)) }
            assertEquals(1, f.resolutions.size)
            f.statusError = 0; f.engine.refresh()
            assertEquals(UploadPhase.SKIPPED, f.store.rows.value.single().phase)
        }
    }
    @Test fun unchangedConflictCannotReleaseUncertainDecisionOrReplayAfterRestart() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            f.store.mutate(row.id) { it.copy(pendingDecision = "keep_target") }
            f.engine.refresh()
            assertEquals("keep_target", f.store.rows.value.single().pendingDecision)
            val restarted = UploadStore(f.directory)
            val engine = UploadEngine(restarted, { f.content.inputStream() }, { f.credential },
                { r, c -> DojoApi(r.origin, c.token, 5, OkHttpClient()) }, { 0 })
            engine.resolve(row.id, ResolveConflictIn(decision = "keep_selected", confirmedOverwrite = true, targetMediaId = "target"))
            assertTrue(f.resolutions.isEmpty())
            assertEquals("keep_target", restarted.rows.value.single().pendingDecision)
            f.resolved["saved"] = "aborted"
            engine.refresh()
            assertEquals(UploadPhase.SKIPPED, restarted.rows.value.single().phase)
        }
    }
    @Test fun crossClientKeepTargetUsesAuditRatherThanOfferingExpiryRetry() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            f.conflict()
            f.resolved["saved"] = "aborted"
            f.engine.refresh()
            assertEquals(UploadPhase.SKIPPED, f.store.rows.value.single().phase)
            assertNull(f.store.rows.value.single().issue)
            f.engine.run {}
            assertTrue(f.puts.isEmpty())
        }
    }
    @Test fun pendingKeepTargetDoesNotMislabelAuditedExpiry() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            f.store.mutate(row.id) { it.copy(pendingDecision = "keep_target") }
            f.status = "aborted"
            f.engine.refresh()
            assertEquals(UploadPhase.EXPIRED, f.store.rows.value.single().phase)
        }
    }
    @Test fun abortedStateBeforeAuditCommitCannotReleaseUnknownOutcome() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            f.store.mutate(row.id) { it.copy(pendingDecision = "keep_target") }
            f.resolved["saved"] = "aborted"; f.hideAudit = true
            f.engine.refresh()
            assertEquals("keep_target", f.store.rows.value.single().pendingDecision)
            assertEquals(UploadPhase.CONFLICT, f.store.rows.value.single().phase)
            f.hideAudit = false; f.engine.refresh()
            assertEquals(UploadPhase.SKIPPED, f.store.rows.value.single().phase)
        }
    }
    @Test fun missingUploadIsDefinitiveAndClearsOldPendingDecision() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            f.store.mutate(row.id) { it.copy(pendingDecision = "keep_target") }
            f.error = 404
            f.engine.refresh()
            assertEquals(UploadPhase.EXPIRED, f.store.rows.value.single().phase)
            assertNull(f.store.rows.value.single().pendingDecision)
        }
    }
    @Test fun delayedResolutionCannotMutateNewPairing() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict(); f.delayResolve = true
            val pending = async { f.engine.resolve(row.id, ResolveConflictIn(decision = "keep_target")) }
            f.putStarted.await()
            f.credential = SessionCredential("b".repeat(64), "NEW-SECRET")
            val revision = f.store.rows.value.single().revision
            assertTrue(runCatching { pending.await() }.exceptionOrNull() is CancellationException)
            assertEquals(revision, f.store.rows.value.single().revision)
            assertEquals("NEW-SECRET", f.credential!!.token)
        }
    }
    @Test fun previewChecksTargetAndSessionBeforeAndAfterTransfer() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.conflict()
            val file = f.directory.resolve("preview.jpg")
            assertTrue(runCatching { f.engine.preview(row.id, "wrong", file) }.isFailure)
            assertEquals(0, f.server.requestCount)
            f.server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse = if (request.path == "/api/pairing/me")
                    MockResponse().setBody("""{"id":1,"kind":"device","name":"test","created_at":"now","created_by":"test","last_seen_at":null,"revoked_at":null}""")
                else {
                    f.putStarted.complete(Unit)
                    MockResponse().setBody("preview").setBodyDelay(1, TimeUnit.SECONDS)
                }
            }
            val pending = async { f.engine.preview(row.id, "target", file) }
            f.putStarted.await()
            f.credential = SessionCredential("b".repeat(64), "NEW-SECRET")
            assertTrue(runCatching { pending.await() }.exceptionOrNull() is CancellationException)
            assertFalse(file.exists())
        }
    }
    @Test fun lostCompleteResponseReconcilesQueued() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            f.add(); f.loseComplete = true
            assertEquals(QueueOutcome.IDLE, f.engine.run {})
            f.engine.run {}
            assertEquals(listOf(0L), f.puts)
            assertEquals(1, f.completions)
            assertEquals(0, f.initializations)
            assertEquals(UploadPhase.QUEUED, f.store.rows.value.single().phase)
        }
    }
    @Test fun limitsAndCapacityRejectBeforeTransfer() = runBlocking {
        for ((bytes, max, code) in listOf(Triple(byteArrayOf(), 10L, 0), Triple(ByteArray(11), 10L, 0), Triple(byteArrayOf(1), 10L, 413), Triple(byteArrayOf(1), 10L, 409))) {
            Fixture(bytes).use { f ->
                f.max = max; f.initError = code; f.add(false)
                f.engine.run {}
                assertTrue(f.puts.isEmpty())
                assertEquals(if (code == 0) 0 else 1, f.initializations)
                assertNotNull(f.store.rows.value.single().issue)
            }
        }
    }
    @Test fun pauseRaceDoesNotReviveRowOrBlockSibling() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val first = f.add(); val sibling = f.add()
            f.responseDelay = true
            val run = async { f.engine.run {} }
            f.putStarted.await()
            f.store.mutate(first.id) { it.copy(intent = UploadIntent.PAUSED, phase = UploadPhase.PAUSED) }
            f.engine.cancel(first.id)
            run.await()
            assertEquals(UploadIntent.PAUSED, f.store.rows.value.first().intent)
            assertEquals(UploadPhase.PAUSED, f.store.rows.value.first().phase)
            assertEquals(UploadPhase.QUEUED, f.store.rows.value.find { it.id == sibling.id }!!.phase)
        }
    }
    @Test fun fiveFailuresRequireManualRetry() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            f.add(); f.error = 503
            repeat(5) { f.engine.run {}; f.clock += 3_600_000 }
            val requests = f.server.requestCount
            assertEquals(5, f.store.rows.value.single().failures)
            assertEquals(QueueOutcome.IDLE, f.engine.run {})
            assertEquals(requests, f.server.requestCount)
            assertEquals(UploadPhase.RETRYABLE, f.store.rows.value.single().phase)
        }
    }
    @Test fun terminalAndInvalidStatusesStopChunks() = runBlocking {
        for (state in listOf("conflict", "failed", "aborted", "invalid", "404")) {
            Fixture(byteArrayOf(1)).use { f ->
                f.add()
                when (state) { "invalid" -> f.invalid = true; "404" -> f.error = 404; else -> f.status = state }
                f.engine.run {}
                assertTrue(f.puts.isEmpty())
                assertNotEquals(UploadPhase.UPLOADING, f.store.rows.value.single().phase)
            }
        }
    }
    @Test fun sourceChangesAndStorageFailuresStopBeforePut() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            f.add(); f.content[0] = 2
            f.engine.run {}
            assertTrue(f.puts.isEmpty())
            assertEquals(UploadPhase.NEEDS_FILE, f.store.rows.value.single().phase)
        }
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.add(false)
            f.directory.resolve("${row.id}.tmp").mkdir()
            assertEquals(UploadIssue.STORAGE, (runCatching { f.engine.run {} }.exceptionOrNull() as? UploadFailure)?.issue)
            assertTrue(f.puts.isEmpty())
        }
    }
    @Test fun systemStopKeepsActiveIntent() = runBlocking {
        Fixture().use { f ->
            f.add(); f.responseDelay = true
            val run = async { f.engine.run {} }
            f.putStarted.await()
            run.cancelAndJoin()
            assertEquals(UploadIntent.ACTIVE, f.store.rows.value.single().intent)
            assertEquals(0, f.store.rows.value.single().failures)
        }
    }
    @Test fun duplicateRunsDoNotDuplicateChunks() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            f.add(); f.responseDelay = true
            val first = async { f.engine.run {} }
            f.putStarted.await()
            assertEquals(QueueOutcome.IDLE, f.engine.run {})
            first.await()
            assertEquals(listOf(0L), f.puts)
        }
    }
    @Test fun unknownIdInitiationLossRequiresExplicitRetry() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            f.add(false); f.initError = 503
            f.engine.run {}
            assertEquals(UploadPhase.RETRYABLE, f.store.rows.value.single().phase)
            val count = f.server.requestCount
            f.clock = 3_600_000
            assertEquals(QueueOutcome.IDLE, f.engine.run {})
            assertEquals(count, f.server.requestCount)
            assertEquals(1, f.initializations)
        }
    }
    @Test fun lateOldPairingResponseCannotWriteOrClearNewSession() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            f.add(); f.responseDelay = true
            val run = async { f.engine.run {} }
            f.putStarted.await()
            f.credential = SessionCredential("b".repeat(64), "NEW-SECRET")
            val revision = f.store.rows.value.single().revision
            run.await()
            assertEquals(revision, f.store.rows.value.single().revision)
            assertEquals("NEW-SECRET", f.credential!!.token)
            assertEquals(QueueOutcome.IDLE, f.engine.run {})
        }
    }
    @Test fun acknowledgedProgressResetsFailures() = runBlocking {
        Fixture(byteArrayOf(1)).use { f ->
            val row = f.add(); f.error = 503
            f.engine.run {}
            assertEquals(1, f.store.rows.value.single().failures)
            f.error = 0; f.confirmed = 1; f.clock = 30_000
            f.engine.run {}
            assertEquals(0, f.store.rows.value.single().failures)
            assertEquals(UploadPhase.QUEUED, f.store.rows.value.find { it.id == row.id }!!.phase)
        }
    }
}
