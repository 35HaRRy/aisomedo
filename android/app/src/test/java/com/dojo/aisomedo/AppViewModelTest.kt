package com.dojo.aisomedo

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import com.dojo.aisomedo.auth.SessionStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.Before
import org.junit.After
import org.junit.Test
import java.nio.file.Files
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import javax.crypto.KeyGenerator

@OptIn(ExperimentalCoroutinesApi::class)
class AppViewModelTest {
    private val main = StandardTestDispatcher()
    @Before fun setMain() { Dispatchers.setMain(main) }
    @After fun resetMain() { Dispatchers.resetMain() }

    private inner class Fixture(paired: Boolean = false, configure: Boolean = true) : AutoCloseable {
        val dir = Files.createTempDirectory("dojo-vm").toFile()
        private val key = KeyGenerator.getInstance("AES").generateKey()
        val store = SessionStore(dir) { key }
        val server = MockWebServer()
        val codes = ConcurrentHashMap<String, Int>()
        val bodies = ConcurrentHashMap<String, String>()
        var delayPath: String? = null
        val origin: String
        val model: AppViewModel
        private val owner = ViewModelStore()
        init {
            bodies["/api/compat"] = """{"api_version":"0.1.0","android_min_version_code":1,"android_current_version_code":1,"update_url":"https://example.com/update"}"""
            bodies["/api/pairing/validate"] = """{"client_id":1,"kind":"device","token":"DEVICE"}"""
            bodies["/api/pairing/me"] = """{"id":1,"kind":"device","name":"Telefon","created_at":"2026-10-05T12:00:00Z","created_by":"cli","last_seen_at":null,"revoked_at":null}"""
            bodies["/api/setup"] = """{"checklist":[{"key":"pairing","label":"Pairing","complete":true},{"key":"consent","label":"Consent","complete":false}],"ready":false}"""
            bodies["/api/dashboard"] = """{"generated_at":"2026-10-05T12:00:00Z","package":null,"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}"""
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse = MockResponse()
                    .setResponseCode(codes[request.path] ?: 200).setBody(bodies[request.path] ?: "{}")
                    .also { if (request.path == delayPath) it.setBodyDelay(1, TimeUnit.SECONDS) }
            }
            server.start()
            origin = server.url("/").toString().trimEnd('/')
            if (configure) store.setOrigin(origin)
            if (paired) store.saveToken(origin, "DEVICE")
            model = AppViewModel(store, OkHttpClient(), 1, true, SavedStateHandle())
            owner.put("model", model)
        }
        fun await(predicate: (AppUiState) -> Boolean) {
            repeat(500) { main.scheduler.runCurrent(); if (predicate(model.state.value)) return; Thread.sleep(10) }
            fail("State did not arrive: ${model.state.value}")
        }
        override fun close() { owner.clear(); server.shutdown(); dir.deleteRecursively() }
    }

    @Test fun noOriginRequiresAddressWithoutNetwork() = runTest(main.scheduler) {
        Fixture(configure = false).use { f -> f.await { it.phase == Phase.ADDRESS }; assertEquals(0, f.server.requestCount) }
    }
    @Test fun compatibilityBeforePairingThenTokenSavedAndMeValidated() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { it.phase == Phase.PAIRING }
            assertEquals("/api/compat", f.server.takeRequest().path)
            f.model.pair("12345678", "Telefon")
            f.await { it.phase == Phase.READY }
            assertEquals("DEVICE", f.store.readToken(f.origin))
            assertEquals("/api/pairing/validate", f.server.takeRequest().path)
            assertEquals("/api/pairing/me", f.server.takeRequest().path)
            assertEquals("consent", f.model.state.value.step)
        }
    }
    @Test fun readyInstallationOpensDashboardAndDoesNotReopenSetupAfterRefresh() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/setup"] = """{"checklist":[],"ready":true}"""
            f.await { it.phase == Phase.READY }
            assertNull(f.model.state.value.step)
            f.model.refresh(); f.await { !it.busy }
            assertNull(f.model.state.value.step)
        }
    }
    @Test fun incompleteSetupOpensOnlyOnce() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY }
            f.model.closeSetup(); f.model.refresh(); f.await { !it.busy }
            assertNull(f.model.state.value.step)
        }
    }
    @Test fun invalidCodeIsDifferentFromAuthenticated401() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.codes["/api/pairing/validate"] = 401
            f.await { it.phase == Phase.PAIRING }
            f.model.pair("bad", "Telefon"); f.await { it.issue == UiIssue.INVALID_CODE }
            assertEquals(Phase.PAIRING, f.model.state.value.phase)
            assertNull(f.store.readToken(f.origin))
        }
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY }
            f.codes["/api/dashboard"] = 401
            f.model.refresh(); f.await { it.phase == Phase.PAIRING }
            assertNull(f.store.readToken(f.origin)); assertNull(f.model.state.value.client)
        }
    }
    @Test fun updateBlocksButRetainsCredential() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY }
            f.codes["/api/dashboard"] = 426
            f.bodies["/api/dashboard"] = """{"update_url":"https://example.com/update"}"""
            f.model.refresh(); f.await { it.phase == Phase.UPDATE_REQUIRED }
            assertEquals("DEVICE", f.store.readToken(f.origin))
        }
    }
    @Test fun lateOldServerResponseCannotResurrectSession() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.delayPath = "/api/dashboard"
            f.await { it.client != null }
            f.model.changeServer()
            f.await { it.phase == Phase.ADDRESS }
            Thread.sleep(1100); main.scheduler.runCurrent()
            assertEquals(Phase.ADDRESS, f.model.state.value.phase)
            assertNull(f.model.state.value.dashboard)
            assertNull(f.store.readToken(f.origin))
        }
    }
    @Test fun malformedDeviceTokenDoesNotEnterReady() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.bodies["/api/pairing/validate"] = """{"client_id":1,"kind":"device"}"""
            f.await { it.phase == Phase.PAIRING }; f.model.pair("12345678", "Telefon")
            f.await { it.issue != null }
            assertEquals(Phase.PAIRING, f.model.state.value.phase)
            assertNull(f.store.readToken(f.origin))
        }
    }
    @Test fun failedCredentialSaveDoesNotEnterReady() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { it.phase == Phase.PAIRING }
            f.dir.resolve("credential.bin").mkdir()
            f.dir.resolve("credential.bin/block").writeText("block")
            f.model.pair("12345678", "Telefon")
            f.await { it.issue == UiIssue.STORAGE }
            assertEquals(Phase.PAIRING, f.model.state.value.phase)
            assertNull(f.model.state.value.client)
        }
    }
}
