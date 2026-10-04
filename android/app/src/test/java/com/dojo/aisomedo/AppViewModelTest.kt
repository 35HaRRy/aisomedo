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
            bodies["/api/settings/plan"] = """{"anchor_date":"2026-10-05","anchor_time":"18:30:00","enabled":false,"timezone":"Europe/Istanbul"}"""
            bodies["/api/settings/branding"] = """{"caption_template":"Eski","intro_asset":null,"intro_duration":null,"logo_asset":"logo.png","outro_asset":null,"outro_duration":null}"""
            bodies["/api/setup/consent"] = """{"accepted_at":null,"text":"Politika metni","version":1}"""
            bodies["/api/setup/consent/accept"] = """{"accepted_at":"2026-10-05T12:00:00Z","version":1}"""
            bodies["/api/meta/status"] = """{"health":"not_connected"}"""
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
            f.await { it.phase == Phase.READY && !it.busy }
            assertEquals("DEVICE", f.store.readToken(f.origin))
            assertEquals("/api/pairing/validate", f.server.takeRequest().path)
            assertEquals("/api/pairing/me", f.server.takeRequest().path)
            assertEquals("consent", f.model.state.value.step)
        }
    }
    @Test fun readyInstallationOpensDashboardAndDoesNotReopenSetupAfterRefresh() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/setup"] = """{"checklist":[],"ready":true}"""
            f.await { it.phase == Phase.READY && !it.busy }
            assertNull(f.model.state.value.step)
            f.model.refresh(); f.await { !it.busy }
            assertNull(f.model.state.value.step)
        }
    }
    @Test fun incompleteSetupOpensOnlyOnce() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
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
            f.await { it.phase == Phase.READY && !it.busy }
            f.codes["/api/dashboard"] = 401
            f.model.refresh(); f.await { it.phase == Phase.PAIRING }
            assertNull(f.store.readToken(f.origin)); assertNull(f.model.state.value.client)
        }
    }
    @Test fun updateBlocksButRetainsCredential() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
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
    @Test fun validDisabledMondayPlanSendsLocalTimeAndRejectsTuesday() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.savePlan("2026-10-06", "18:30", false)
            assertEquals(UiIssue.INVALID_INPUT, f.model.state.value.issue)
            f.model.savePlan("2026-10-05", "18:30", false)
            f.await { !it.busy }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val put = requests.single { it.method == "PUT" }
            assertEquals("/api/settings/plan", put.path)
            assertEquals("""{"anchor_date":"2026-10-05","anchor_time":"18:30","enabled":false}""", put.body.readUtf8())
        }
    }
    @Test fun captionPatchOnlyChangesCaptionAndFailedSaveRetainsStepAndDraft() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("caption_template"); f.await { !it.busy }
            f.model.setDraft("caption", "Yeni", "caption_template")
            f.codes["/api/settings/branding"] = 422
            f.model.saveCaption("Yeni"); f.await { !it.busy }
            assertEquals("caption_template", f.model.state.value.step)
            assertEquals("Yeni", f.model.state.value.drafts["caption"])
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("""{"caption_template":"Yeni"}""", requests.single { it.method == "PATCH" }.body.readUtf8())
        }
    }
    @Test fun changedPolicyAndConflictClearAcknowledgementWithoutAutoAccept() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.consent != null && !it.busy }
            f.model.acknowledgeConsent(true)
            f.bodies["/api/setup/consent"] = """{"accepted_at":null,"text":"Yeni politika","version":2}"""
            f.model.refresh(); f.await { it.consent?.version == 2 && !it.busy }
            assertFalse(f.model.state.value.consentAcknowledged)
            f.model.acknowledgeConsent(true)
            f.codes["/api/setup/consent/accept"] = 409
            f.model.acceptConsent(2); f.await { !it.busy }
            assertEquals(UiIssue.POLICY_CHANGED, f.model.state.value.issue)
            assertFalse(f.model.state.value.consentAcknowledged)
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("""{"version":2}""", requests.single { it.method == "POST" }.body.readUtf8())
        }
    }
    @Test fun inheritedAcceptanceAndMissingPolicyDoNotPost() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/setup/consent"] = """{"accepted_at":"2026-10-05T12:00:00Z","text":"Politika","version":1}"""
            f.await { it.consent != null && !it.busy }
            f.model.acceptConsent(1)
            f.codes["/api/setup/consent"] = 404
            f.model.reloadStep("consent"); f.await { !it.busy }
            assertNull(f.model.state.value.consent)
            assertEquals(UiIssue.POLICY_MISSING, f.model.state.value.issue)
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertTrue(requests.none { it.method == "POST" })
        }
    }
    @Test fun dirtyDraftSurvivesRemoteRefreshAndExplicitReloadReplacesIt() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.branding != null && !it.busy }
            f.model.setDraft("caption", "Taslak", "caption_template")
            f.bodies["/api/settings/branding"] = f.bodies["/api/settings/branding"]!!.replace("Eski", "Uzak")
            f.model.refresh(); f.await { !it.busy }
            assertEquals("Taslak", f.model.state.value.drafts["caption"])
            assertTrue("caption_template" in f.model.state.value.changedSteps)
            assertEquals("Taslak", f.model.saved.get<String>("draft_caption"))
            f.model.reloadStep("caption_template"); f.await { !it.busy }
            assertEquals("Uzak", f.model.state.value.drafts["caption"])
        }
    }
    @Test fun readinessDoesNotSkipCardsAndFinishChecksServer() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/setup"] = """{"checklist":[{"key":"caption_template","label":"Caption","complete":true},{"key":"cards","label":"Cards","complete":false,"required":false}],"ready":true}"""
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("caption_template"); f.await { !it.busy }; f.model.nextStep()
            assertEquals("cards", f.model.state.value.step)
            f.model.finishSetup(); f.await { !it.busy }
            assertNull(f.model.state.value.step)
        }
    }
}
