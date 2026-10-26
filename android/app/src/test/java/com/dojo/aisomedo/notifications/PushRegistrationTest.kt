package com.dojo.aisomedo.notifications

import com.dojo.aisomedo.auth.SessionStore
import com.dojo.aisomedo.offline.SnapshotStore
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import javax.crypto.KeyGenerator

class PushRegistrationTest {
    @Test fun disconnectedOrUnsupportedAccessCannotRegisterOrRemoveToken() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope, allowed = { _, _ -> false })
            try {
                f.server.enqueue(MockResponse().setBody("{}"))
                registration.refresh("TOKEN")
                withTimeout(5000) { while (registration.busy) delay(10) }
                registration.stopSession()
                assertNull(withContext(Dispatchers.IO) { f.server.takeRequest(300, TimeUnit.MILLISECONDS) })
            } finally { scope.cancel() }
        }
    }
    @Test fun backgroundVersionRejectionPersistsBeforeFailureSignal() = runBlocking {
        Fixture().use { f ->
            val snapshots = SnapshotStore(f.directory.resolve("offline"))
            snapshots.update(f.origin) { it.copy(updateUrl = "https://dojo.example/release") }
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope, snapshots)
            try {
                f.server.enqueue(MockResponse().setResponseCode(426).setBody("{}"))
                registration.refresh("TOKEN")
                withTimeout(5000) { while (registration.busy) delay(10) }
                assertEquals(426, registration.failure.value?.status)
                val cached = snapshots.read(f.origin, f.store.readSession(f.origin)!!.bindingId)!!
                assertEquals(5, cached.rejectedVersionCode)
                assertEquals("https://dojo.example/release", cached.updateUrl)
                assertFalse(registration.ready.value)
            } finally { scope.cancel() }
        }
    }
    @Test fun receivedRejectionAfterDisconnectStillStopsSessionAndPersistsUpdate() = runBlocking {
        Fixture().use { f ->
            val snapshots = SnapshotStore(f.directory.resolve("offline"))
            val allowed = AtomicBoolean(true)
            val rejected = AtomicInteger()
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope, snapshots,
                { _, _ -> allowed.get() }, { rejected.set(it.status) })
            try {
                f.server.enqueue(MockResponse().setResponseCode(426)
                    .setBody("""{"update_url":"https://dojo.example/new-release"}""").setBodyDelay(200, TimeUnit.MILLISECONDS))
                registration.refresh("TOKEN")
                assertNotNull(withContext(Dispatchers.IO) { f.server.takeRequest(5, TimeUnit.SECONDS) })
                allowed.set(false)
                withTimeout(5000) { while (registration.busy) delay(10) }
                val cached = snapshots.read(f.origin, f.store.readSession(f.origin)!!.bindingId)!!
                assertEquals(5, cached.rejectedVersionCode)
                assertEquals("https://dojo.example/new-release", cached.updateUrl)
                assertEquals(426, rejected.get())
            } finally { scope.cancel() }
        }
    }
    @Test fun repeatedSameFailureCannotReportAvailableUntilSuccessfulRegistration() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope)
            try {
                repeat(2) {
                    f.server.enqueue(MockResponse().setResponseCode(503).setBody("{}"))
                    registration.refresh("SAME")
                    withTimeout(5000) { while (registration.busy) delay(10) }
                    assertEquals(PushAvailability.REGISTRATION_FAILED,
                        registrationAvailability(PushAvailability.AVAILABLE, registration.ready.value, registration.failure.value))
                }
                f.server.enqueue(MockResponse().setBody("{}"))
                registration.refresh("SAME")
                assertEquals(PushAvailability.REGISTRATION_FAILED,
                    registrationAvailability(PushAvailability.AVAILABLE, registration.ready.value, registration.failure.value))
                withTimeout(5000) { while (registration.busy) delay(10) }
                assertEquals(PushAvailability.AVAILABLE,
                    registrationAvailability(PushAvailability.AVAILABLE, registration.ready.value, registration.failure.value))
                assertEquals(PushAvailability.PERMISSION_DENIED,
                    registrationAvailability(PushAvailability.PERMISSION_DENIED, registration.ready.value, registration.failure.value))
            } finally { scope.cancel() }
        }
    }
    private class Fixture : AutoCloseable {
        val directory = Files.createTempDirectory("push-session").toFile()
        val key = KeyGenerator.getInstance("AES").generateKey()
        val store = SessionStore(directory) { key }
        val server = MockWebServer().apply { start() }
        val origin = server.url("/").toString().trimEnd('/')
        init { store.setOrigin(origin); store.saveToken(origin, "SYNTHETIC_DEVICE") }
        override fun close() { server.shutdown(); directory.deleteRecursively() }
    }
    @Test fun successfulRegistrationDeduplicatesAndRotationUsesCapturedSession() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope)
            try {
                f.server.enqueue(MockResponse().setBody("{}"))
                registration.refresh("FIRST")
                val first = withContext(Dispatchers.IO) { f.server.takeRequest(5, TimeUnit.SECONDS)!! }
                assertEquals("PUT", first.method)
                assertEquals("Bearer SYNTHETIC_DEVICE", first.getHeader("Authorization"))
                assertEquals("{\"token\":\"FIRST\"}", first.body.readUtf8())
                withTimeout(5000) { while (registration.busy) delay(10) }
                registration.refresh("FIRST")
                assertNull(withContext(Dispatchers.IO) { f.server.takeRequest(200, TimeUnit.MILLISECONDS) })
                f.server.enqueue(MockResponse().setBody("{}"))
                registration.refresh("ROTATED")
                val second = withContext(Dispatchers.IO) { f.server.takeRequest(5, TimeUnit.SECONDS)!! }
                assertEquals("{\"token\":\"ROTATED\"}", second.body.readUtf8())
                withTimeout(5000) { while (registration.busy) delay(10) }
                assertNull(registration.failure.value)
            } finally { scope.cancel() }
        }
    }
    @Test fun failedRegistrationRetriesNextRefreshWithoutDiscardingCredentials() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope)
            try {
                f.server.enqueue(MockResponse().setResponseCode(503).setBody("{}"))
                registration.refresh("FIRST")
                withTimeout(5000) { while (registration.busy) delay(10) }
                assertEquals(503, registration.failure.value!!.status)
                assertEquals(f.store.readSession(f.origin)!!.bindingId, registration.failure.value!!.bindingId)
                f.server.enqueue(MockResponse().setBody("{}"))
                registration.refresh("FIRST")
                withTimeout(5000) { while (registration.busy) delay(10) }
                assertNull(registration.failure.value)
                assertEquals(2, f.server.requestCount)
                assertEquals("SYNTHETIC_DEVICE", f.store.readToken(f.origin))
            } finally { scope.cancel() }
        }
    }
    @Test fun lateRegistrationCannotPublishFailureOrTokenIntoNewServerSession() = runBlocking {
        for (status in listOf(401, 426)) Fixture().use { f -> MockWebServer().use { other ->
            other.start()
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope)
            try {
                f.server.enqueue(MockResponse().setResponseCode(status).setBody("{}").setBodyDelay(1, TimeUnit.SECONDS))
                registration.refresh("OLD")
                assertNotNull(withContext(Dispatchers.IO) { f.server.takeRequest(5, TimeUnit.SECONDS) })
                val next = other.url("/").toString().trimEnd('/')
                f.store.setOrigin(next); f.store.saveToken(next, "NEW_DEVICE")
                withTimeout(5000) { while (registration.busy) delay(10) }
                assertNull(registration.failure.value)
                assertEquals("NEW_DEVICE", f.store.readToken(next))
                f.server.enqueue(MockResponse().setBody("{}")) // best-effort old registration removal
                other.enqueue(MockResponse().setBody("{}"))
                registration.refresh("NEW")
                val request = withContext(Dispatchers.IO) { other.takeRequest(5, TimeUnit.SECONDS)!! }
                assertEquals("Bearer NEW_DEVICE", request.getHeader("Authorization"))
                assertEquals("{\"token\":\"NEW\"}", request.body.readUtf8())
            } finally { scope.cancel() }
        } }
    }
    @Test fun rotationWhileRegistrationBusyEventuallySendsOnlyNewestToken() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope)
            try {
                f.server.enqueue(MockResponse().setBody("{}").setBodyDelay(300, TimeUnit.MILLISECONDS))
                f.server.enqueue(MockResponse().setBody("{}"))
                registration.refresh("FIRST")
                assertNotNull(withContext(Dispatchers.IO) { f.server.takeRequest(5, TimeUnit.SECONDS) })
                registration.refresh("SECOND"); registration.refresh("LATEST")
                val next = withContext(Dispatchers.IO) { f.server.takeRequest(5, TimeUnit.SECONDS)!! }
                assertEquals("{\"token\":\"LATEST\"}", next.body.readUtf8())
                withTimeout(5000) { while (registration.busy) delay(10) }
                assertEquals(2, f.server.requestCount)
            } finally { scope.cancel() }
        }
    }
    @Test fun stopAfterProcessRestartRemovesOldRegistrationWithoutClearingCredentials() = runBlocking {
        Fixture().use { f ->
            val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
            val registration = PushRegistration(f.store, OkHttpClient(), 5, scope)
            try {
                f.server.enqueue(MockResponse().setBody("{}"))
                registration.stopSession()
                val request = withContext(Dispatchers.IO) { f.server.takeRequest(5, TimeUnit.SECONDS) }
                assertNotNull(request)
                assertEquals("DELETE", request!!.method)
                assertEquals("Bearer SYNTHETIC_DEVICE", request.getHeader("Authorization"))
                assertEquals("SYNTHETIC_DEVICE", f.store.readToken(f.origin))
            } finally { scope.cancel() }
        }
    }
}
