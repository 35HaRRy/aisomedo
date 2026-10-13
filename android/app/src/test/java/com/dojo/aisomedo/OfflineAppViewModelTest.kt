package com.dojo.aisomedo

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.SessionStore
import com.dojo.aisomedo.offline.*
import com.dojo.aisomedo.editor.RangeInput
import com.dojo.aisomedo.reviews.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.*
import org.junit.Assert.*
import org.junit.*
import java.nio.file.Files
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.KeyGenerator

@OptIn(ExperimentalCoroutinesApi::class)
class OfflineAppViewModelTest {
    private val main = StandardTestDispatcher()
    @Before fun setup() { Dispatchers.setMain(main) }
    @After fun teardown() { Dispatchers.resetMain() }
    private inner class Fixture(connected: Boolean = false, cached: Boolean = true) : AutoCloseable {
        val directory = Files.createTempDirectory("offline-model").toFile()
        @Volatile var key = KeyGenerator.getInstance("AES").generateKey()
        val keyHook = AtomicReference<(() -> Unit)?>(null)
        val keyThreads = CopyOnWriteArrayList<String>()
        val store = SessionStore(directory.resolve("session")) { keyThreads.add(Thread.currentThread().name); keyHook.getAndSet(null)?.invoke(); key }
        val snapshots = SnapshotStore(directory.resolve("offline"))
        val server = MockWebServer()
        val network = MutableStateFlow(NetworkStatus(connected))
        val codes = ConcurrentHashMap<String, Int>()
        val seen = CopyOnWriteArrayList<String>()
        var delayDashboard = false
        var folder = "active"
        var delayAsset = false
        val owner = ViewModelStore()
        val origin: String
        var model: AppViewModel
        val client = ClientOut("now", "cli", 1, "device", null, "Telefon", null)
        fun dashboard() = """{"generated_at":"2026-10-12T12:00:00Z","package":{"id":1,"folder_name":"$folder","created_at":"now","status":"active"},"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}"""
        val editor = """{"package":{"id":1,"folder_name":"active","created_at":"now","status":"active"},"media":[],"montage":{"card_duration":0,"clips":[],"combined_duration":0,"duration_complete":true,"max_duration_seconds":90,"order":[],"over_limit":false,"required_action":null,"selections":{},"trims":{}},"render_stale":false,"render_preview_url":null,"render_revision":null}"""
        init {
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    val path = request.requestUrl!!.encodedPath
                    seen.add("${request.method} $path")
                    val body = when (path) {
                        "/api/compat" -> """{"api_version":"0.1","android_min_version_code":1,"android_current_version_code":5,"update_url":"https://dojo.example/release"}"""
                        "/api/pairing/me" -> """{"id":1,"name":"${if (request.getHeader("Authorization")?.contains("NEW") == true) "New" else "Telefon"}","kind":"device","created_at":"now","created_by":"cli","last_seen_at":null,"revoked_at":null}"""
                        "/api/setup" -> """{"checklist":[],"ready":true}"""
                        "/api/dashboard" -> dashboard()
                        "/api/packages/active/editor" -> editor
                        "/api/activity" -> """{"events":[],"next_cursor":null}"""
                        "/api/reviews/7" -> """{"next_regular_at":null,"preview_url":"/api/packages/active/render/preview?revision=exact","render_ready":true,"review":{"caption":"Exact","created_at":"now","id":7,"occurrence_id":2,"package_folder":"active","revision_digest":"exact","status":"pending","version":3}}"""
                        "/api/settings/plan" -> """{"anchor_date":"2026-10-12","anchor_time":"18:30:00","enabled":false,"timezone":"Europe/Istanbul"}"""
                        "/api/settings/branding" -> """{"caption_template":"Old","intro_asset":null,"intro_duration":null,"logo_asset":null,"outro_asset":null,"outro_duration":null}"""
                        "/api/settings/branding/assets" -> """{"asset":"branding/assets/new.png","preview_url":"/api/settings/branding/assets/new.png"}"""
                        "/api/setup/consent" -> """{"version":1,"text":"Policy","accepted_at":null}"""
                        "/api/meta/status" -> """{"health":"not_connected"}"""
                        else -> "{}"
                    }
                    return MockResponse().setResponseCode(codes[path] ?: 200).setBody(body).apply {
                        if (delayDashboard && path == "/api/dashboard") setBodyDelay(1, TimeUnit.SECONDS)
                        if (delayAsset && path == "/api/settings/branding/assets") setBodyDelay(1, TimeUnit.SECONDS)
                    }
                }
            }
            server.start()
            origin = server.url("/").toString().trimEnd('/')
            store.setOrigin(origin); store.saveToken(origin, "SYNTHETIC")
            if (cached) snapshots.update(origin) { it.copy(compat = CompatInfo("0.1", 1, 5, "https://dojo.example/release"), updateUrl = "https://dojo.example/release",
                data = CachedContent(store.readSession(origin)!!.bindingId, client, SetupOut(emptyList(), true),
                    dashboard = Json.decodeFromString(dashboard()), editor = Json.decodeFromString(editor),
                    activity = ActivityPageOut(emptyList(), null), dashboardFetchedAt = 100, editorFetchedAt = 100, activityFetchedAt = 100)) }
            model = create()
        }
        fun create(version: Int = 1): AppViewModel = AppViewModel(store, OkHttpClient(), version, true,
            SavedStateHandle(mapOf("draft_caption" to "Draft")), snapshots, network, { 200 }).also { owner.put("model", it) }
        fun await(predicate: (AppUiState) -> Boolean) {
            repeat(700) { main.scheduler.runCurrent(); if (predicate(model.state.value)) return; Thread.sleep(10) }
            fail("State did not arrive: ${model.state.value}")
        }
        fun connect() { network.value = NetworkStatus(true, network.value.epoch + 1) }
        fun disconnect() { network.value = NetworkStatus(false, network.value.epoch + 1); main.scheduler.runCurrent() }
        fun settle() { repeat(30) { main.scheduler.runCurrent(); Thread.sleep(10) } }
        override fun close() { owner.clear(); server.shutdown(); directory.deleteRecursively() }
    }
    @Test fun coldOfflineStartRestoresHistoricalSections() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            assertEquals("active", f.model.state.value.editor.snapshot!!.`package`.folderName)
            assertEquals(100L, f.model.state.value.activityFetchedAt)
            assertTrue(f.model.state.value.activity!!.events.isEmpty())
            assertFalse(f.model.state.value.canMutate)
            f.model.navigate(Destination.PACKAGE); f.model.navigate(Destination.ACTIVITY); f.settle()
            assertEquals(Destination.ACTIVITY, f.model.state.value.destination)
            assertEquals(0, f.server.requestCount)
        }
    }
    @Test fun offlineMissAndEmptyHistoryDiffer() = runTest(main.scheduler) {
        Fixture(cached = false).use { f ->
            f.await { !it.busy }
            assertNull(f.model.state.value.activityFetchedAt)
            assertNull(f.model.state.value.activity)
            assertEquals(Phase.CONNECTION_ERROR, f.model.state.value.phase)
            assertEquals(0, f.server.requestCount)
        }
    }
    @Test fun disconnectBlocksDirectWritesAndPreservesDrafts() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.model.selectStep("caption_template"); f.await { !it.busy }
            f.model.setDraft("caption", "Unsaved", "caption_template")
            f.disconnect(); val before = f.server.requestCount
            f.model.setDraft("caption", "Blocked", "caption_template")
            f.model.saveCaption("Blocked"); f.model.savePlan("2026-10-12", "18:30", true)
            f.model.acknowledgeConsent(true); f.model.acceptConsent(1); f.model.skipCards()
            f.model.startOAuth { fail("OAuth must not open offline") }; f.model.connectInstagramToken("blocked")
            f.model.uploadAsset("logo_asset", byteArrayOf(1)); f.model.reorderMedia(emptyList())
            f.model.removeMedia("media"); f.model.restoreMedia("media"); f.model.editRanges("media", listOf(RangeInput("1", "3")))
            f.model.saveMediaTrims(); f.model.refresh(); f.settle()
            assertEquals(before, f.server.requestCount)
            assertEquals("Unsaved", f.model.state.value.drafts["caption"])
            assertFalse(f.model.state.value.canMutate)
        }
    }
    @Test fun connectionChangeBeforeCollectorStartsIsObserved() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.connect()
            f.await { it.canMutate }
            assertTrue(f.model.state.value.networkConnected)
        }
    }
    @Test fun reconnectWaitsForFreshResourceReads() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { !it.busy }; f.codes["/api/packages/active/editor"] = 500; f.codes["/api/activity"] = 500
            f.connect(); f.await { !it.busy && f.server.requestCount >= 6 }
            assertFalse(f.model.state.value.canEditMedia)
            assertEquals(100L, f.model.state.value.activityFetchedAt)
            f.codes["/api/settings/plan"] = 500
            f.model.selectStep("schedule"); f.await { !it.busy }
            assertFalse("schedule" in f.model.state.value.configurationFresh)
            val before = f.seen.count { it.startsWith("PUT") }
            f.model.savePlan("2026-10-12", "18:30", true); f.settle()
            assertEquals(before, f.seen.count { it.startsWith("PUT") })
        }
    }
    @Test fun replacementPackageInvalidatesOldEditor() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { !it.busy }; f.folder = "replacement"; f.codes["/api/packages/active/editor"] = 500
            f.connect(); f.await { !it.busy && f.server.requestCount >= 6 }
            assertNull(f.model.state.value.editor.snapshot)
            assertNull(f.snapshots.read(f.origin, f.store.readSession(f.origin)!!.bindingId)!!.data!!.editor)
        }
    }
    @Test fun delayedOldSessionCannotCommitCache() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; val reads = f.seen.count { it == "GET /api/dashboard" }
            f.delayDashboard = true; f.model.refresh()
            f.await { f.seen.count { it == "GET /api/dashboard" } > reads }
            f.store.saveToken(f.origin, "NEW-SYNTHETIC")
            val binding = f.store.readSession(f.origin)!!.bindingId
            f.snapshots.update(f.origin) { it.copy(data = CachedContent(binding, f.client.copy(name = "New"), SetupOut(emptyList(), true))) }
            Thread.sleep(1200); f.settle()
            assertEquals("New", f.snapshots.read(f.origin, binding)!!.data!!.client.name)
            assertEquals("New", f.model.state.value.client?.name)
        }
    }
    @Test fun cacheWriteFailureAfterAcceptedWriteDoesNotReplay() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.model.selectStep("caption_template"); f.await { !it.busy }
            f.directory.resolve("offline/snapshot.tmp").mkdir()
            f.model.saveCaption("Submitted"); f.await { !it.busy }
            assertEquals(UiIssue.STORAGE, f.model.state.value.issue)
            f.model.refresh(); f.await { !it.busy }
            assertEquals(1, f.seen.count { it == "PATCH /api/settings/branding" })
        }
    }
    @Test fun unsupportedStateSurvivesRestartAndFailedRefresh() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.codes["/api/compat"] = 426; f.model.refresh(); f.await { it.phase == Phase.UPDATE_REQUIRED }
            f.disconnect(); val before = f.server.requestCount
            f.model = f.create(); f.await { it.phase == Phase.UPDATE_REQUIRED && !it.busy }
            f.model.refresh(); f.settle()
            assertEquals(Phase.UPDATE_REQUIRED, f.model.state.value.phase)
            assertEquals("https://dojo.example/release", f.model.state.value.updateUrl)
            assertEquals(before, f.server.requestCount)
            f.model = f.create(2); f.await { !it.busy }
            assertEquals(Phase.READY, f.model.state.value.phase)
        }
    }
    @Test fun unpairedMinimumGatePersistsWithoutProtectedContent() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { !it.busy }; f.store.clearToken()
            f.snapshots.update(f.origin) { it.copy(compat = CompatInfo("0.1", 2, 5, "https://dojo.example/release"), data = null) }
            f.model = f.create(); f.await { it.phase == Phase.UPDATE_REQUIRED && !it.busy }
            assertEquals(0, f.server.requestCount)
        }
    }
    @Test fun revocationCannotFallBackToProtectedCache() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.codes["/api/pairing/me"] = 401; f.model.refresh(); f.await { it.phase == Phase.PAIRING && !it.busy }
            assertNull(f.store.readSession(f.origin))
            assertNull(f.snapshots.read(f.origin, null)!!.data)
            assertNull(f.model.state.value.activity)
        }
    }
    @Test fun immediateDisconnectCannotEditOrSubmitBeforeCollectorRuns() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.model.selectStep("caption_template"); f.await { !it.busy }
            val draft = f.model.state.value.drafts["caption"]
            val before = f.seen.count { it.startsWith("PATCH") }
            f.network.value = NetworkStatus(false, 1)
            assertFalse(f.model.writesAllowed)
            f.model.setDraft("caption", "Must not change", "caption_template")
            assertEquals(draft, f.model.state.value.drafts["caption"])
            f.model.saveCaption("Must not send"); f.settle()
            assertEquals(before, f.seen.count { it.startsWith("PATCH") })
        }
    }
    @Test fun newNetworkEpochCannotSubmitBeforeRevalidation() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.model.selectStep("caption_template"); f.await { !it.busy }
            val before = f.seen.count { it.startsWith("PATCH") }
            f.network.value = NetworkStatus(true, 2)
            assertFalse(f.model.writesAllowed)
            f.model.saveCaption("Old authority"); f.settle()
            assertEquals(before, f.seen.count { it.startsWith("PATCH") })
        }
    }
    @Test fun delayedAssetRemainsPendingUntilExplicitFreshRetry() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.model.selectStep("logo"); f.await { !it.busy }
            f.delayAsset = true; f.model.uploadAsset("logo_asset", byteArrayOf(1))
            f.await { "POST /api/settings/branding/assets" in f.seen }
            f.network.value = NetworkStatus(false, 1); main.scheduler.runCurrent()
            f.network.value = NetworkStatus(true, 2)
            f.await { !it.busy && f.model.state.value.pendingAssets.isNotEmpty() }
            assertEquals(0, f.seen.count { it == "PATCH /api/settings/branding" })
            assertEquals("branding/assets/new.png", f.model.state.value.pendingAssets["logo_asset"]?.asset)
            f.model.selectStep("logo"); f.await { !it.busy }
            f.model.retryAsset("logo_asset"); f.await { !it.busy }
            assertEquals(1, f.seen.count { it == "POST /api/settings/branding/assets" })
            assertEquals(1, f.seen.count { it == "PATCH /api/settings/branding" })
        }
    }
    @Test fun credentialReadFailureCannotDeleteReplacement() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { !it.busy }
            f.key = KeyGenerator.getInstance("AES").generateKey()
            f.keyHook.set { f.store.saveToken(f.origin, "NEW-SYNTHETIC") }
            f.model.refresh(); f.await { !it.busy }
            assertEquals("NEW-SYNTHETIC", f.store.readToken(f.origin))
            assertNull(f.model.state.value.client)
        }
    }
    @Test fun credentialReadFailureCannotEraseNewServerCache() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.await { !it.busy }
            val newOrigin = "https://new.example"
            f.key = KeyGenerator.getInstance("AES").generateKey()
            f.keyHook.set {
                f.store.setOrigin(newOrigin); f.store.saveToken(newOrigin, "NEW-SYNTHETIC")
                val binding = f.store.readSession(newOrigin)!!.bindingId
                f.snapshots.update(newOrigin) { it.copy(data = CachedContent(binding, f.client.copy(name = "New"), SetupOut(emptyList(), true))) }
            }
            f.model.refresh(); f.await { !it.busy }
            assertEquals("NEW-SYNTHETIC", f.store.readToken(newOrigin))
            assertEquals("New", f.snapshots.read(newOrigin, f.store.readSession(newOrigin)!!.bindingId)!!.data!!.client.name)
            assertEquals(newOrigin, f.model.state.value.origin)
        }
    }
    @Test fun replacementDuringOfflineRestoreCannotShowOldSnapshot() = runTest(main.scheduler) {
        Fixture().use { f ->
            f.keyHook.set { f.store.saveToken(f.origin, "NEW-SYNTHETIC") }
            f.await { !it.busy }
            assertNull(f.model.state.value.client)
            assertNull(f.model.state.value.dashboard)
            assertNull(f.model.state.value.activity)
        }
    }
    @Test fun credentialVerificationRunsOffMainThread() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }; f.model.selectStep("caption_template"); f.await { !it.busy }
            f.keyThreads.clear()
            f.model.saveCaption("Submitted"); f.await { !it.busy }
            assertTrue(f.keyThreads.isNotEmpty())
            assertTrue("Credential IO ran on main test thread: ${f.keyThreads}", f.keyThreads.none { it.startsWith("Test worker") })
        }
    }
    @Test fun queuedOldBackgroundFailureCannotAffectNewPairing() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }
            val old = f.store.readSession(f.origin)!!.bindingId
            f.model.observeSessionFailure(com.dojo.aisomedo.uploads.UploadIssue.AUTH, old)
            f.store.saveToken(f.origin, "NEW-SYNTHETIC")
            f.await { it.client?.name == "New" && !it.busy }
            assertEquals("NEW-SYNTHETIC", f.store.readToken(f.origin))
        }
    }
    @Test fun immediateDisconnectBlocksReviewDecisionBeforeCollectorRuns() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }
            f.model.openReview(ReviewTarget(reviewId = 7))
            f.await { it.review.detail != null && !it.review.busy }
            f.model.markReviewPreviewReady(7, "exact", true)
            assertTrue(f.model.state.value.review.canApprove)
            val before = f.server.requestCount
            f.network.value = NetworkStatus(false, 1)
            f.model.approveReview()
            f.model.requestReviewAction(ReviewAction.SKIP)
            f.model.skipReview()
            f.settle()
            assertEquals(before, f.server.requestCount)
            assertFalse(f.model.state.value.review.canApprove)
        }
    }
    @Test fun reconnectRequiresFreshReviewAndPreviewBeforeApproval() = runTest(main.scheduler) {
        Fixture(connected = true).use { f ->
            f.await { it.canMutate }
            f.model.openReview(ReviewTarget(reviewId = 7))
            f.await { it.review.detail != null && !it.review.busy }
            f.model.markReviewPreviewReady(7, "exact", true)
            f.disconnect()
            f.codes["/api/reviews/7"] = 500
            f.connect(); f.await { it.canMutate && !it.review.busy }
            val before = f.seen.count { it.startsWith("POST") }
            f.model.markReviewPreviewReady(7, "exact", true)
            f.model.approveReview(); f.settle()
            assertEquals(before, f.seen.count { it.startsWith("POST") })
            assertFalse(f.model.state.value.review.canApprove)
            f.codes.remove("/api/reviews/7")
            f.model.refreshReview(); f.await { !it.review.busy && !it.review.readRequired }
            assertFalse(f.model.state.value.review.previewReady)
        }
    }
}
