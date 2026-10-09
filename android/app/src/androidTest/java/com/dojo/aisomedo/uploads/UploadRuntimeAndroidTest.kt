package com.dojo.aisomedo.uploads

import android.Manifest
import android.content.Intent
import android.os.Build
import android.provider.DocumentsContract
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.dojo.aisomedo.MainActivity
import kotlinx.coroutines.runBlocking
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
                val body = when (path) {
                    "/api/compat" -> """{"api_version":"0.1.0","android_min_version_code":1,"android_current_version_code":5,"update_url":"https://example.com/update"}"""
                    "/api/pairing/me" -> """{"id":1,"kind":"device","name":"Synthetic test","created_at":"now","created_by":"test","last_seen_at":null,"revoked_at":null}"""
                    "/api/setup" -> """{"checklist":[],"ready":true}"""
                    "/api/dashboard" -> """{"generated_at":"2026-10-09T00:00:00Z","package":null,"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"idle"}}"""
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
    fun document(size: Int, unknown: Boolean = false): android.net.Uri {
        val id = (if (unknown) "unknown_" else "known_") + UUID.randomUUID().toString().replace("-", "")
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
        await { runtime.matches(binding) }
        runBlocking { runtime.select(uris.toList()) }
        await { runtime.rows.value.any { it.uri == uris.first().toString() } || runtime.issue.value != null }
    }
    fun await(condition: () -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30)
        while (!condition()) { if (System.nanoTime() >= deadline) throw AssertionError("Synthetic upload condition timed out"); Thread.sleep(25) }
    }
    fun front() { target.startActivity(Intent(target, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)); instrumentation.waitForIdleSync() }
    fun shell(command: String) { instrumentation.uiAutomation.executeShellCommand(command).use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).use { input -> input.readBytes() } } }
    override fun close() {
        front()
        runtime.rows.value.filter { eligible(it) }.forEach { runtime.pause(it.id) }
        runCatching { await { runtime.rows.value.none(::eligible) } }
        runtime.rows.value.forEach { runtime.dismiss(it.id) }
        runCatching { await { runtime.rows.value.isEmpty() } }
        runtime.stopSession()
        runtime.sessionStore.clearTokenIfBinding(origin, binding)
        scenario.close()
        server.close()
        documents.forEach { (uri, file) -> test.revokeUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION); file.delete() }
    }
}

class UploadRuntimeAndroidTest {
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
