package com.dojo.aisomedo.uploads

import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.SessionCredential
import kotlinx.coroutines.*
import kotlinx.serialization.json.Json
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
        var clock = 0L
        var credential: SessionCredential? = SessionCredential("a".repeat(64), "TEST-ONLY")
        val putStarted = CompletableDeferred<Unit>()
        val engine: UploadEngine
        init {
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    val path = request.requestUrl!!.encodedPath
                    if (path == "/api/pairing/me") return MockResponse().setBody("""{"id":1,"kind":"device","name":"test","created_at":"now","created_by":"test","last_seen_at":null,"revoked_at":null}""")
                    if (error != 0) return MockResponse().setResponseCode(error)
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
                    val out = UploadOut(declaredSizeBytes = content.size.toLong(), receivedBytes = confirmed,
                        receivedRanges = if (confirmed > 0) listOf(listOf(0, confirmed)) else emptyList(), status = status, uploadId = if (invalid) "wrong" else "saved")
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
