package com.dojo.aisomedo.uploads

import android.Manifest
import android.content.Intent
import android.os.Build
import android.provider.DocumentsContract
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.dojo.aisomedo.MainActivity
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.async
import kotlinx.coroutines.Dispatchers
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** Use only on a dedicated test emulator: credentials/documents are synthetic. */
internal class UploadDeviceFixture : AutoCloseable {
    val instrumentation = InstrumentationRegistry.getInstrumentation()
    val target = instrumentation.targetContext
    private val test = instrumentation.context
    val runtime = UploadRuntime.get(target)
    val server = MockWebServer()
    val initializationCount = AtomicInteger()
    val dashboardReads = AtomicInteger()
    val offsets = CopyOnWriteArrayList<Pair<String, Long>>()
    data class Remote(val size: Long, @Volatile var received: Long = 0, @Volatile var phase: String = "receiving")
    val uploads = ConcurrentHashMap<String, Remote>()
    @Volatile var max = 16L * CHUNK_BYTES
    @Volatile var failure = 0
    @Volatile var losePut = false
    @Volatile var delayMillis = 0L
    val origin: String
    val binding: String
    val scenario: ActivityScenario<MainActivity>
    private val documents = mutableListOf<Pair<android.net.Uri, File>>()
    init {
        runtime.stopSession()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.requestUrl!!.encodedPath
                if (path == "/api/dashboard") dashboardReads.incrementAndGet()
                val body = when (path) {
                    "/api/compat" -> """{"api_version":"0.1.0","android_min_version_code":1,"android_current_version_code":5,"update_url":"https://example.com/update"}"""
                    "/api/pairing/me" -> """{"id":1,"kind":"device","name":"Synthetic test","created_at":"now","created_by":"test","last_seen_at":null,"revoked_at":null}"""
                    "/api/setup" -> """{"checklist":[],"ready":true}"""
                    "/api/dashboard" -> """{"generated_at":"2026-10-09T00:00:00Z","package":null,"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"idle"}}"""
                    "/api/activity" -> """{"events":[],"next_cursor":null}"""
                    "/api/media/upload-limits" -> """{"max_file_bytes":$max,"max_package_bytes":$max,"active_package_id":0}"""
                    else -> null
                }
                if (failure != 0 && path.contains("/uploads/")) return MockResponse().setResponseCode(failure)
                if (body != null) return MockResponse().setBody(body)
                val id = if (path == "/api/media/uploads") {
                    val json = kotlinx.serialization.json.Json.parseToJsonElement(request.body.readUtf8()) as kotlinx.serialization.json.JsonObject
                    val size = json["declared_size_bytes"].toString().toLong()
                    "synthetic-${initializationCount.incrementAndGet()}".also { uploads[it] = Remote(size) }
                } else path.removePrefix("/api/media/uploads/").substringBefore('/')
                val remote = uploads[id] ?: return MockResponse().setResponseCode(404)
                if (request.method == "PUT") {
                    val offset = request.requestUrl!!.queryParameter("offset")!!.toLong()
                    offsets.add(id to offset)
                    remote.received = maxOf(remote.received, offset + request.body.size)
                    if (losePut) { losePut = false; return MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST) }
                }
                if (path.endsWith("complete")) remote.phase = "queued"
                val ranges = if (remote.received == 0L) "[]" else "[[0,${remote.received}]]"
                return MockResponse().setBody("""{"upload_id":"$id","declared_size_bytes":${remote.size},"received_bytes":${remote.received},"received_ranges":$ranges,"status":"${remote.phase}"}""")
                    .apply { if (request.method == "PUT") setBodyDelay(delayMillis, TimeUnit.MILLISECONDS) }
            }
        }
        server.start()
        origin = server.url("/").toString().trimEnd('/')
        runtime.sessionStore.setOrigin(origin)
        runtime.sessionStore.saveToken(origin, "SYNTHETIC-DEVICE-ONLY")
        binding = runtime.sessionStore.readSession(origin)!!.bindingId
        if (Build.VERSION.SDK_INT >= 33) instrumentation.uiAutomation.grantRuntimePermission(target.packageName, Manifest.permission.POST_NOTIFICATIONS)
        scenario = ActivityScenario.launch(MainActivity::class.java)
        runtime.attach(origin, 1)
    }
    fun document(size: Int, unknown: Boolean = false, delayed: Boolean = false): android.net.Uri {
        val id = (if (delayed) "delay_" else "") + (if (unknown) "unknown_" else "known_") + UUID.randomUUID().toString().replace("-", "")
        val uri = DocumentsContract.buildDocumentUri("com.dojo.aisomedo.test.documents", id)
        val file = File(test.cacheDir, "upload-test-$id")
        FileOutputStream(file).use { output ->
            val chunk = ByteArray(CHUNK_BYTES) { (it % 251).toByte() }
            var left = size
            while (left > 0) { val count = minOf(left, chunk.size); output.write(chunk, 0, count); left -= count }
        }
        test.grantUriPermission(target.packageName, uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        documents.add(uri to file)
        return uri
    }
    fun select(vararg uris: android.net.Uri) {
        // Attach is an async action; allow the real session observer to finish first.
        awaitWritable()
        runtime.setWriteAccess(origin, binding, true)
        await { runtime.matches(binding) }
        runBlocking { runtime.select(uris.toList()) }
        await { runtime.rows.value.any { it.uri == uris.first().toString() } || runtime.issue.value != null }
    }
    fun awaitWritable() {
        await {
            var ready = false
            scenario.onActivity { ready = androidx.lifecycle.ViewModelProvider(it)[com.dojo.aisomedo.AppViewModel::class.java].writesAllowed }
            ready
        }
    }
    fun await(condition: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
        while (!condition()) { if (System.nanoTime() >= deadline) throw AssertionError("Synthetic upload condition timed out"); Thread.sleep(25) }
    }
    fun front() { target.startActivity(Intent(target, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)); instrumentation.waitForIdleSync() }
    fun shell(command: String) { instrumentation.uiAutomation.executeShellCommand(command).use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).use { input -> input.readBytes() } } }
    fun shellText(command: String): String = instrumentation.uiAutomation.executeShellCommand(command).use {
        android.os.ParcelFileDescriptor.AutoCloseInputStream(it).use { input -> input.readBytes().toString(Charsets.UTF_8) }
    }
    fun offline(block: () -> Unit) {
        val wifi = shellText("settings get global wifi_on").trim()
        val data = shellText("settings get global mobile_data").trim()
        val connected = runtime.network.state.value.connected
        try {
            shell("svc wifi disable"); shell("svc data disable")
            await { !runtime.network.state.value.connected }
            block()
        } finally {
            shell("svc wifi ${if (wifi == "1") "enable" else "disable"}")
            shell("svc data ${if (data == "1") "enable" else "disable"}")
            if (connected) await { runtime.network.state.value.connected }
        }
    }
    override fun close() {
        front()
        runtime.rows.value.filter { eligible(it) }.forEach { runtime.pause(it.id) }
        runCatching { await { runtime.rows.value.none(::eligible) } }
        if (runtime.matches(binding)) {
            runtime.rows.value.forEach { runtime.dismiss(it.id) }
            runCatching { await { runtime.rows.value.isEmpty() } }
        }
        runtime.stopSession()
        runtime.sessionStore.clearTokenIfBinding(origin, binding)
        scenario.close()
        server.close()
        documents.forEach { (uri, file) -> test.revokeUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION); file.delete() }
    }
}

class UploadRuntimeAndroidTest {
    @Test fun enqueuedSelectionWaitsForForegroundWriteAccess() {
        UploadDeviceFixture().use { f ->
            f.awaitWritable()
            f.await { f.runtime.writeAccess.value == f.binding }
            val uri = f.document(3)
            f.runtime.setWriteAccess(f.origin, f.binding, false)
            f.runtime.enqueue(listOf(uri))
            f.instrumentation.waitForIdleSync()
            assertTrue(f.runtime.rows.value.isEmpty())
            f.runtime.setWriteAccess(f.origin, f.binding, true)
            f.await { f.runtime.rows.value.singleOrNull()?.uri == uri.toString() }
        }
    }
    @Test fun waitingSelectionCannotCrossPairingChange() {
        UploadDeviceFixture().use { f ->
            f.awaitWritable()
            f.await { f.runtime.writeAccess.value == f.binding }
            val uri = f.document(3)
            f.runtime.setWriteAccess(f.origin, f.binding, false)
            f.runtime.enqueue(listOf(uri))
            f.runtime.sessionStore.saveToken(f.origin, "DIFFERENT-SYNTHETIC-DEVICE")
            val binding = f.runtime.sessionStore.readSession(f.origin)!!.bindingId
            try {
                f.runtime.attach(f.origin, 1)
                f.runtime.setWriteAccess(f.origin, binding, true)
                f.await { !f.runtime.matches(f.binding) }
                f.instrumentation.waitForIdleSync()
                assertTrue(f.runtime.rows.value.isEmpty())
                assertFalse(f.target.contentResolver.persistedUriPermissions.any { it.uri == uri })
            } finally { f.runtime.sessionStore.clearTokenIfBinding(f.origin, binding) }
        }
    }
    @Test fun offlineResumeRegistersConstrainedWorkBeforeProcessDeath() {
        UploadDeviceFixture().use { f ->
            f.delayMillis = 1500; f.select(f.document(CHUNK_BYTES * 4)); f.await { f.offsets.isNotEmpty() }
            val row = f.runtime.rows.value.single()
            f.runtime.pause(row.id); f.await { f.runtime.rows.value.single().intent == UploadIntent.PAUSED }
            f.offline {
                val requests = f.server.requestCount
                f.runtime.resume(row.id); f.await { f.runtime.rows.value.single().intent == UploadIntent.ACTIVE }
                f.await {
                    if (Build.VERSION.SDK_INT >= 34) f.target.getSystemService(android.app.job.JobScheduler::class.java).forNamespace("dojo-uploads")
                        .getPendingJob(3300)?.extras?.getString("binding") == f.binding
                    else androidx.work.WorkManager.getInstance(f.target).getWorkInfosForUniqueWork("dojo-upload-${f.binding}").get().any { !it.state.isFinished }
                }
                assertEquals(requests, f.server.requestCount)
            }
        }
    }
    @Test fun delayedDocumentCannotCommitAfterAuthorityRevocation() = runBlocking {
        UploadDeviceFixture().use { f ->
            f.await { f.runtime.network.state.value.connected }
            f.awaitWritable()
            f.runtime.attach(f.origin, 1); f.runtime.setWriteAccess(f.origin, f.binding, true)
            val uri = f.document(3, delayed = true)
            val selection = async(Dispatchers.IO) { f.runtime.select(listOf(uri)) }
            f.await { f.target.contentResolver.persistedUriPermissions.any { it.uri == uri } }
            f.runtime.setWriteAccess(f.origin, f.binding, false)
            selection.await()
            assertTrue(f.runtime.rows.value.isEmpty())
            assertFalse(f.target.contentResolver.persistedUriPermissions.any { it.uri == uri })
        }
    }
    @Test fun delayedReplacementRetainsOriginalAndReleasesNewGrant() {
        UploadDeviceFixture().use { f ->
            f.delayMillis = 1500; f.select(f.document(CHUNK_BYTES * 3)); f.await { f.offsets.isNotEmpty() }
            val original = f.runtime.rows.value.single()
            f.runtime.pause(original.id); f.await { f.runtime.rows.value.single().intent == UploadIntent.PAUSED }
            val replacement = f.document(CHUNK_BYTES * 3, delayed = true)
            f.runtime.setWriteAccess(f.origin, f.binding, true)
            f.runtime.resume(original.id, replacement)
            f.await { f.target.contentResolver.persistedUriPermissions.any { it.uri == replacement } }
            f.runtime.setWriteAccess(f.origin, f.binding, false)
            f.await { f.target.contentResolver.persistedUriPermissions.none { it.uri == replacement } }
            assertEquals(original.uri, f.runtime.rows.value.single().uri)
            assertEquals(UploadIntent.PAUSED, f.runtime.rows.value.single().intent)
            assertEquals(original.identity, f.runtime.rows.value.single().identity)
        }
    }
    @Test fun background426PersistsBeforeSessionStops() {
        UploadDeviceFixture().use { f ->
            f.select(f.document(3)); f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.QUEUED }
            f.scenario.close()
            f.failure = 426
            runBlocking { f.runtime.refresh() }
            val cached = f.runtime.snapshots.read(f.origin, f.binding)!!
            assertEquals(com.dojo.aisomedo.BuildConfig.VERSION_CODE, cached.rejectedVersionCode)
            assertEquals("https://example.com/update", cached.updateUrl)
            assertEquals(UploadIssue.UPDATE_REQUIRED, f.runtime.issue.value)
        }
    }
    @Test fun offlineMutationAndLatePickerCallbacksAreRejected() {
        UploadDeviceFixture().use { f ->
            f.delayMillis = 1500
            f.select(f.document(CHUNK_BYTES * 3 + 1)); f.await { f.offsets.isNotEmpty() }
            f.offline {
                val row = f.runtime.rows.value.single()
                f.runtime.pause(row.id); f.await { f.runtime.rows.value.single().intent == UploadIntent.PAUSED }
                val paused = f.runtime.rows.value.single()
                val requests = f.server.requestCount
                f.runtime.resume(row.id); f.await { f.runtime.rows.value.single().intent == UploadIntent.ACTIVE }
                val replacement = f.document(3)
                runBlocking { f.runtime.select(listOf(replacement)) }
                f.runtime.resume(row.id, replacement); f.runtime.retry(row.id); f.runtime.dismiss(row.id)
                f.runtime.resolve(row.id, com.dojo.aisomedo.api.ResolveConflictIn(decision = "keep_both"))
                Thread.sleep(300)
                assertEquals(1, f.runtime.rows.value.size)
                assertEquals(paused.identity, f.runtime.rows.value.single().identity)
                assertEquals(paused.status, f.runtime.rows.value.single().status)
                assertEquals(row.uri, f.runtime.rows.value.single().uri)
                assertEquals(requests, f.server.requestCount)
            }
        }
    }
    @Test fun pushRejectionStopsSharedRuntimeWithoutVisibleActivity() {
        for (status in listOf(401, 426)) UploadDeviceFixture().use { f ->
            f.select(f.document(3)); f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.QUEUED }
            f.scenario.close()
            f.runtime.observePushFailure(f.origin, f.binding, status, "https://example.com/signed-update")
            assertFalse(f.runtime.matches(f.binding))
            if (status == 401) {
                assertNull(f.runtime.sessionStore.readSession(f.origin))
                assertNull(f.runtime.snapshots.read(f.origin, null)?.data)
                assertEquals(UploadIssue.AUTH, f.runtime.issue.value)
            } else {
                val cached = f.runtime.snapshots.read(f.origin, f.binding)!!
                assertEquals(com.dojo.aisomedo.BuildConfig.VERSION_CODE, cached.rejectedVersionCode)
                assertEquals("https://example.com/signed-update", cached.updateUrl)
                assertFalse(f.runtime.canRegisterPush(f.origin, f.binding))
                assertEquals(UploadIssue.UPDATE_REQUIRED, f.runtime.issue.value)
            }
        }
    }
    @Test fun sharedUriDismissalRetainsOtherRowsAndOriginalFile() {
        UploadDeviceFixture().use { f ->
            val uri = f.document(3)
            f.select(uri, uri)
            f.await { f.runtime.rows.value.size == 2 && f.runtime.rows.value.all { it.phase == UploadPhase.QUEUED } }
            val first = f.runtime.rows.value.first().id
            f.runtime.dismiss(first)
            f.await { f.runtime.rows.value.size == 1 }
            assertTrue(f.target.contentResolver.persistedUriPermissions.any { it.uri == uri })
            assertEquals(3, UploadSource(f.target.contentResolver).open(uri.toString()).use { it.readBytes().size })
            f.runtime.dismiss(f.runtime.rows.value.single().id)
            f.await { f.runtime.rows.value.isEmpty() }
            assertFalse(f.target.contentResolver.persistedUriPermissions.any { it.uri == uri })
        }
    }
    @Test fun revokedSessionClearsOnlyMatchingPairing() {
        UploadDeviceFixture().use { f ->
            f.select(f.document(3))
            f.await { f.runtime.rows.value.singleOrNull()?.phase == UploadPhase.QUEUED }
            f.failure = 401
            runBlocking { f.runtime.refresh() }
            assertNull(f.runtime.sessionStore.readSession(f.origin))
            assertEquals(UploadIssue.AUTH, f.runtime.issue.value)
            assertEquals(f.binding, f.runtime.failureBinding)
        }
    }
}
