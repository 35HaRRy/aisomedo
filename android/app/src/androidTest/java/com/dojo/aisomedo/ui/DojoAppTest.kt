package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.runtime.mutableStateOf
import kotlinx.coroutines.flow.MutableStateFlow
import com.dojo.aisomedo.offline.NetworkStatus
import com.dojo.aisomedo.reviews.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import androidx.test.platform.app.InstrumentationRegistry
import com.dojo.aisomedo.*
import com.dojo.aisomedo.auth.SessionStore
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.*
import org.junit.*
import javax.crypto.KeyGenerator
import com.dojo.aisomedo.api.*
import androidx.compose.foundation.layout.Column

class DojoAppTest {
    @get:Rule val compose = createComposeRule()
    private val server = MockWebServer()
    private val owner = ViewModelStore()
    private lateinit var model: AppViewModel
    private val paths = java.util.concurrent.CopyOnWriteArrayList<String>()
    private var blocked = false
    private var emptyPending = false
    private val network = MutableStateFlow(NetworkStatus(true))
    @Before fun setup() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                paths.add(request.method + " " + request.path)
                if (blocked) return MockResponse().setResponseCode(426).setBody("{}")
                if (request.path == "/api/events") return MockResponse().setHeader("Content-Type", "text/event-stream")
                    .setBody("event: ready\ndata: {\"protocol\":1}\n\n" + "event: heartbeat\ndata: {}\n\n".repeat(20_000))
                    .throttleBody(64, 100, java.util.concurrent.TimeUnit.MILLISECONDS)
                if (request.path == "/api/packages/active/editor") return MockResponse().setResponseCode(404)
                val body = when (request.path) {
                    "/api/compat" -> """{"api_version":"0.1.0","android_min_version_code":1,"android_current_version_code":1,"update_url":"https://example.com/update"}"""
                    "/api/pairing/me" -> """{"id":1,"kind":"device","name":"Telefon","created_at":"2026-10-05T12:00:00Z","created_by":"cli","last_seen_at":null,"revoked_at":null}"""
                    "/api/setup" -> """{"checklist":[],"ready":true}"""
                    "/api/packages" -> "[]"
                    "/api/settings/plan" -> """{"anchor_date":"2026-10-05","anchor_time":"18:30:00","enabled":false,"timezone":"Europe/Istanbul"}"""
                    "/api/settings/branding" -> """{"caption_template":"Dojo #training","intro_asset":null,"intro_duration":null,"logo_asset":null,"outro_asset":null,"outro_duration":null}"""
                    "/api/settings/reminders" -> """{"interval_minutes":60,"delivery_start":"09:00:00","delivery_end":"21:00:00","timezone":"Europe/Istanbul"}"""
                    "/api/meta/status" -> """{"health":"expired","ig_username":"dojo"}"""
                    "/api/meta/oauth/start" -> """{"attempt_id":"attempt-1","auth_url":"https://www.facebook.com/oauth?state=synthetic"}"""
                    "/api/setup/consent" -> """{"accepted_at":null,"text":"Politika metni","version":2}"""
                    "/api/activity?limit=50" -> """{"events":[{"id":1,"action":"package.created","actor":"system","occurred_at":"2026-10-12T12:00:00Z","details":{}}],"next_cursor":null}"""
                    "/api/reviews/7" -> """{"next_regular_at":"2099-10-19T10:00:00+03:00","preview_url":"/api/packages/active/render/preview","render_ready":true,"review":{"caption":"Exact caption","created_at":"2026-10-11T10:00:00+03:00","id":7,"occurrence_id":2,"package_folder":"active","revision_digest":"exact","status":"pending","version":3}}"""
                    "/api/dashboard" -> if (emptyPending) """{"generated_at":"2026-10-05T12:00:00Z","package":null,"next_slot":null,"pending_actions":[{"due_at":"2026-10-05T12:00:00Z","occurrence_id":2,"review_id":null,"version":null,"package_folder":"active","state":"empty_package"}],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}""" else """{"generated_at":"2026-10-05T12:00:00Z","package":null,"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}"""
                    else -> """{"generated_at":"2026-10-05T12:00:00Z","package":null,"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}"""
                }
                return MockResponse().setBody(body)
            }
        }
        server.start()
        val key = KeyGenerator.getInstance("AES").generateKey()
        val directory = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir.resolve("ui-test-session").apply { deleteRecursively(); mkdirs() }
        val store = SessionStore(directory) { key }
        val origin = server.url("/").toString().trimEnd('/')
        store.setOrigin(origin); store.saveToken(origin, "SYNTHETIC")
        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            model = AppViewModel(store, OkHttpClient(), 1, true, SavedStateHandle(), network = network)
            owner.put("test", model)
            model.setForeground(true)
        }
    }
    @After fun teardown() {
        InstrumentationRegistry.getInstrumentation().runOnMainSync { owner.clear() }
        server.shutdown()
    }
    @Test fun fiveDestinationsAreDistinctAndPackageDoesNotCreate() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(10000) { model.state.value.canMutate && model.state.value.activity != null }
        compose.onNodeWithText("Bekleyen işlemler").assertDoesNotExist()
        compose.onNodeWithText("Paket", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Henüz aktif paket yok").assertExists()
        compose.onNodeWithText("Tamamlananlar", useUnmergedTree = true).performClick()
        compose.waitUntil(10000) { model.state.value.completedPackages != null }
        compose.onNodeWithText("Henüz tamamlanmış paket yok.").assertExists()
        compose.onNodeWithText("Hareketler", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Onay kutusu").assertExists()
        compose.onNodeWithText("package.created").assertExists()
        androidx.test.espresso.Espresso.pressBack()
        compose.onNodeWithText("Bekleyen işlemler").assertDoesNotExist()
        compose.onNodeWithText("Ayarlar", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Sunucuyu değiştir").performScrollTo().performClick()
        compose.onNodeWithText("Bu cihazın yeniden eşleştirilmesi gerekecek.").assertExists()
        compose.onNodeWithText("Vazgeç").performClick()
        Assert.assertTrue(paths.none { it.startsWith("POST /api/packages") })
    }
    @Test fun emptyPendingOpensPackageEditorWithoutReviewContinuation() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(10000) { model.state.value.canMutate }
        compose.runOnIdle { emptyPending = true; model.refresh() }
        compose.waitUntil(10000) { model.state.value.canMutate && model.state.value.dashboard?.pendingActions?.isNotEmpty() == true }
        compose.onNodeWithText("Pakete git").performScrollTo().performClick()
        compose.onNodeWithText("Aktif Paket").assertExists()
        compose.onNodeWithTag("review-continue").assertDoesNotExist()
        compose.runOnIdle {
            Assert.assertEquals(Destination.PACKAGE, model.state.value.destination)
            Assert.assertNull(model.state.value.review.target)
        }
        Assert.assertTrue(paths.none { it.startsWith("POST ") })
    }
    @Test fun backClosesFocusedReviewToOwningActivityWithoutSubmitting() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(5000) { model.state.value.phase == Phase.READY && !model.state.value.busy }
        compose.runOnIdle {
            model.navigate(Destination.ACTIVITY)
            model.openReview(com.dojo.aisomedo.reviews.ReviewTarget(reviewId = 7))
        }
        compose.onNodeWithText("Yayın incelemesi").assertExists()
        androidx.test.espresso.Espresso.pressBack()
        compose.onNodeWithText("Onay kutusu").assertExists()
        Assert.assertEquals(Destination.ACTIVITY, model.state.value.destination)
        Assert.assertNull(model.state.value.review.target)
        Assert.assertTrue(paths.none { it.contains("/approve") || it.contains("/skip") || it.contains("/reschedule") })
    }
    @Test fun switchesAtExactly600Dp() {
        val width = mutableStateOf(599)
        compose.setContent { Box(Modifier.requiredWidth(width.value.dp)) { DojoApp(model) {} } }
        compose.waitUntil(10000) { model.state.value.phase == Phase.READY }
        compose.onNodeWithTag("navigation-bar").assertExists()
        compose.runOnIdle { width.value = 600 }
        compose.onNodeWithTag("navigation-rail").assertExists()
        compose.onNodeWithTag("navigation-bar").assertDoesNotExist()
    }
    @Test fun updateGateHidesMutationsAndNavigation() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(10000) { model.state.value.phase == Phase.READY }
        compose.runOnIdle { blocked = true; model.refresh() }
        compose.waitUntil(10000) { model.state.value.phase == Phase.UPDATE_REQUIRED }
        compose.onNodeWithText("Güncelleme gerekli").assertExists()
        compose.onNodeWithTag("navigation-bar").assertDoesNotExist()
        compose.onNodeWithText("Kurulumu aç").assertDoesNotExist()
    }
    @Test fun dashboardIncludesEveryPendingStateAndHealth() {
        val time = "2026-10-05T12:00:00Z"
        val oneoff = DashboardSlotOut("2026-10-06T12:00:00Z", "oneoff")
        val regular = DashboardSlotOut("2026-10-19T12:00:00Z", "regular")
        val dashboard = DashboardOut(time, DashboardInstagramOut("healthy", "dojo"), true, oneoff, listOf(oneoff, regular), null,
            listOf("review_ready", "empty_package", "preparing").mapIndexed { i, state -> DashboardActionOut(time, i, null, null, null, state, null) },
            PlanOut(null, null, false, "Europe/Istanbul"), DashboardWorkerOut("busy", "healthy"))
        compose.setContent { DojoTheme { Column { DashboardScreen(dashboard, SetupOut(emptyList(), true), false, true, {}, {}) } } }
        listOf("İnceleme hazır", "Paket boş", "Hazırlanıyor", "dojo", "Çalışıyor", "Henüz aktif paket yok", "Tek seferlik yayın", "Düzenli yayın").forEach {
            compose.onNodeWithText(it).assertExists()
        }
        compose.onNodeWithText("Bilgiler henüz alınamadı. Tekrar deneyin.").assertDoesNotExist()
    }
    @Test fun futureOneoffCanChangeDateWithoutRegularSlot() {
        val slot = DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 8)
        val dashboard = DashboardOut("2026-10-05T12:00:00Z", DashboardInstagramOut("healthy"), false, slot, listOf(slot), null,
            emptyList(), PlanOut(null, null, false, "Europe/Istanbul"), DashboardWorkerOut(null, "healthy"))
        var changed: DashboardSlotOut? = null
        compose.setContent { DojoTheme { Column {
            DashboardScreen(dashboard, null, false, false, {}, {}, onChangeOneoffDate = { value, _, _ -> changed = value })
        } } }
        compose.onNodeWithText("Tarihi değiştir").performClick()
        compose.onNodeWithText("Kaydet").performClick()
        compose.runOnIdle { Assert.assertEquals(slot, changed) }
    }

    @Test fun futureOneoffDecisionsRequireSkipConfirmationAndRespectStaleState() {
        val slot = DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 8)
        val dashboard = DashboardOut(generatedAt = "2026-08-03T10:00:00+03:00", instagram = DashboardInstagramOut("unknown"),
            nextSlot = slot, nextSlots = listOf(slot), `package` = null, pendingActions = emptyList(),
            plan = PlanOut(null, null, false, "Europe/Istanbul"), worker = DashboardWorkerOut(null, "healthy"))
        val stale = mutableStateOf(false)
        val decisions = mutableListOf<Pair<DashboardSlotOut, Boolean>>()
        compose.setContent { DojoTheme { Column {
            DashboardScreen(dashboard, null, stale.value, false, {}, {}, onDecideOneoff = { value, skip -> decisions.add(value to skip) })
        } } }
        compose.onNodeWithText("Atla").performClick()
        compose.runOnIdle { Assert.assertTrue(decisions.isEmpty()) }
        compose.onNodeWithText("Atlamayı onayla").performClick()
        compose.runOnIdle { Assert.assertEquals(listOf(slot to true), decisions) }
        compose.onNodeWithText("İncele ve yayınla").performClick()
        compose.runOnIdle { Assert.assertEquals(listOf(slot to true, slot to false), decisions); stale.value = true }
        compose.onNodeWithText("İncele ve yayınla").assertIsNotEnabled()
        compose.onNodeWithText("Atla").assertIsNotEnabled()
    }

    @Test fun settingsExposeEditorsReconnectAndReadOnlyConsentWithoutWizard() {
        val urls = mutableListOf<String>()
        compose.setContent { DojoApp(model) { urls.add(it) } }
        compose.waitUntil(10000) { model.state.value.canMutate }
        compose.onNodeWithText("Ayarlar", useUnmergedTree = true).performClick()
        compose.waitUntil(10000) { model.state.value.canConfigure("reminders") }
        Assert.assertNull(model.state.value.step)
        compose.onNodeWithText("Kurulumu aç").assertDoesNotExist()
        compose.onNodeWithText("Kaldır").performScrollTo().assertExists()
        compose.onNodeWithTag("settings-schedule").assertExists()
        compose.onNodeWithTag("reminder-interval").performScrollTo().assertTextContains("60")
        compose.onNodeWithTag("reminder-save").assertIsEnabled()
        compose.onNodeWithTag("settings-logo").assertExists()
        compose.onNodeWithTag("settings-cards").assertExists()
        compose.onNodeWithText("Dojo #training").performScrollTo().assertExists()
        compose.onNodeWithText("Instagram ile yetkilendir").performScrollTo().performClick()
        compose.waitUntil(10000) { urls.isNotEmpty() }
        Assert.assertEquals(listOf("https://www.facebook.com/oauth?state=synthetic"), urls)
        compose.onNodeWithText("Politika metni").performScrollTo().assertExists()
        compose.onNodeWithTag("consent-acknowledgement").assertDoesNotExist()
        compose.onNodeWithText("Bu sürümü kabul et").assertDoesNotExist()
        compose.onNodeWithText("Kartları değiştirmeden devam et").assertDoesNotExist()
        Assert.assertTrue(paths.none { it == "POST /api/setup/consent/accept" })
    }
    @Test fun settingsOfflineDisablesReminderWritesAndReconnect() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(10000) { model.state.value.canMutate }
        compose.runOnIdle { model.navigate(Destination.SETTINGS) }
        compose.waitUntil(10000) { model.state.value.canConfigure("reminders") }
        compose.runOnIdle { network.value = NetworkStatus(false, 1) }
        compose.waitUntil(5000) { !model.state.value.networkConnected }
        compose.onNodeWithTag("reminder-save").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("Instagram ile yetkilendir").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("Politika metni").performScrollTo().assertExists()
        compose.onNodeWithTag("navigation-bar").assertExists()
    }
    @Test fun offlineCacheRemainsNavigableWithTimestampAndApprovalInbox() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(10000) { model.state.value.canMutate }
        compose.runOnIdle { network.value = NetworkStatus(false, 1) }
        compose.waitUntil(5000) { !model.state.value.networkConnected }
        compose.onNodeWithTag("offline-notice").assertExists()
        compose.onNodeWithText("Paket", useUnmergedTree = true).performClick()
        compose.onNodeWithTag("package-fetched-at").assertExists()
        compose.onNodeWithText("Hareketler", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Onay kutusu").assertExists()
        compose.onNodeWithText("package.created").assertExists()
        compose.onNodeWithTag("activity-fetched-at").assertExists()
        compose.onNodeWithTag("navigation-bar").assertExists()
    }
    @Test fun historyMissingAndEmptyHaveDifferentCopy() {
        val page = mutableStateOf<ActivityPageOut?>(null)
        compose.setContent { DojoTheme { ActivityScreen(page.value, if (page.value == null) null else 100, false) {} } }
        compose.onNodeWithText("Bu bölüm için kayıtlı bilgi yok. Bağlanıp yenileyin.").assertExists()
        compose.runOnIdle { page.value = ActivityPageOut(emptyList(), null) }
        compose.onNodeWithText("Henüz hareket kaydı yok.").assertExists()
        compose.onNodeWithText("Bu bölüm için kayıtlı bilgi yok. Bağlanıp yenileyin.").assertDoesNotExist()
    }
    @Test fun missingUpdateUrlExplainsUnavailableDownload() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(10000) { model.state.value.canMutate }
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = MockResponse().setBody("""{"api_version":"0.1","android_min_version_code":2,"android_current_version_code":2,"update_url":"javascript:alert(1)"}""")
        }
        compose.runOnIdle { model.refresh() }
        compose.waitUntil(10000) { model.state.value.phase == Phase.UPDATE_REQUIRED }
        compose.onNodeWithText("Güvenli güncelleme adresi alınamadı. Yeniden deneyin veya sunucuyu değiştirin.").assertExists()
        compose.onNodeWithTag("navigation-bar").assertDoesNotExist()
    }
    private fun showOfflineReview(action: ReviewAction) {
        compose.waitUntil(10000) { model.state.value.canMutate }
        InstrumentationRegistry.getInstrumentation().runOnMainSync { model.openReview(ReviewTarget(reviewId = 7, action = action)) }
        compose.waitUntil(5000) { model.state.value.review.detail != null && !model.state.value.review.busy }
        InstrumentationRegistry.getInstrumentation().runOnMainSync { network.value = NetworkStatus(false, 1) }
        compose.waitUntil(5000) { !model.state.value.networkConnected }
        compose.setContent { DojoApp(model) {} }
    }
    @Test fun offlineReviewBlocksDecisionsAndPreviewButKeepsNavigation() {
        showOfflineReview(ReviewAction.RESCHEDULE)
        compose.onNodeWithTag("review-approve").assertIsNotEnabled()
        compose.onNodeWithTag("review-skip").assertIsNotEnabled()
        compose.onNodeWithTag("review-reschedule").assertIsNotEnabled()
        compose.onNodeWithTag("review-confirm-reschedule").assertIsNotEnabled()
        compose.onNodeWithTag("review-date").assertIsNotEnabled()
        compose.onNodeWithTag("review-time").assertIsNotEnabled()
        compose.onNodeWithTag("review-offline-preview").assertExists()
        compose.onNodeWithTag("navigation-bar").assertExists()
        compose.onNodeWithTag("review-close").performScrollTo().performClick()
        compose.onNodeWithText("Bekleyen işlemler").assertExists()
        Assert.assertTrue(paths.none { it.contains("/render/preview") || it.contains("/approve") || it.contains("/skip") || it.contains("/reschedule") })
    }
    @Test fun offlineReviewCannotConfirmPreviouslyOpenedSkip() {
        showOfflineReview(ReviewAction.SKIP)
        compose.onNodeWithTag("review-confirm-skip").assertIsNotEnabled()
        Assert.assertTrue(paths.none { it.contains("/skip") })
    }
    @Test fun offlineInboxAndContinuationCannotInvokeReviewActions() {
        val time = "2026-10-05T12:00:00Z"
        val dashboard = DashboardOut(time, DashboardInstagramOut("unknown"), true, null, null, null,
            listOf(DashboardActionOut(time, 2, "active", null, null, "empty_package", null)),
            PlanOut(null, null, false, "Europe/Istanbul"), DashboardWorkerOut(null, "unknown"))
        val state = AppUiState(phase = Phase.READY, networkConnected = false, authoritative = true,
            review = ReviewState(target = ReviewTarget(occurrenceId = 2, packageFolder = "active", action = ReviewAction.UPLOAD), readRequired = false))
        compose.setContent { DojoTheme { Column {
            ApprovalInbox(dashboard, false, {}, { _, _ -> Assert.fail("Offline inbox action") }, canMutate = state.canMutate)
            ReviewContinuation(state.review, state.canMutate, emptyList(), { _, _ -> Assert.fail("Offline continuation") }, {}, {}, {})
        } } }
        compose.onNodeWithText("Medya yükle").assertIsNotEnabled()
        compose.onNodeWithTag("review-continue").assertIsNotEnabled()
        compose.onAllNodesWithText("Atla").assertAll(isNotEnabled())
        compose.onAllNodesWithText("Yeniden zamanla").assertAll(isNotEnabled())
    }
}
