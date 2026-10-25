package com.dojo.aisomedo
import kotlinx.coroutines.async
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonArray

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import com.dojo.aisomedo.auth.SessionStore
import com.dojo.aisomedo.uploads.UploadIssue
import com.dojo.aisomedo.editor.*
import com.dojo.aisomedo.reviews.*
import com.dojo.aisomedo.notifications.*
import com.dojo.aisomedo.uploads.UploadRecord
import com.dojo.aisomedo.uploads.UploadPhase
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
        val seen = java.util.concurrent.CopyOnWriteArrayList<String>()
        val origin: String
        var model: AppViewModel
        val saved = SavedStateHandle()
        val network = kotlinx.coroutines.flow.MutableStateFlow(com.dojo.aisomedo.offline.NetworkStatus(true))
        var stopped = 0
        var tokenAtStop: String? = null
        private val owner = ViewModelStore()
        init {
            bodies["/api/compat"] = """{"api_version":"0.1.0","android_min_version_code":1,"android_current_version_code":1,"update_url":"https://example.com/update"}"""
            bodies["/api/pairing/validate"] = """{"client_id":1,"kind":"device","token":"DEVICE"}"""
            bodies["/api/pairing/me"] = """{"id":1,"kind":"device","name":"Telefon","created_at":"2026-10-05T12:00:00Z","created_by":"cli","last_seen_at":null,"revoked_at":null}"""
            bodies["/api/setup"] = """{"checklist":[{"key":"pairing","label":"Pairing","complete":true},{"key":"consent","label":"Consent","complete":false}],"ready":false}"""
            bodies["/api/dashboard"] = """{"generated_at":"2026-10-05T12:00:00Z","package":{"id":1,"folder_name":"active","created_at":"2026-10-10T12:00:00Z","status":"active"},"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}"""
            bodies["/api/activity?limit=50"] = """{"events":[],"next_cursor":null}"""
            bodies["/api/settings/plan"] = """{"anchor_date":"2026-10-05","anchor_time":"18:30:00","enabled":false,"timezone":"Europe/Istanbul"}"""
            bodies["/api/settings/reminders"] = """{"interval_minutes":60,"delivery_start":"09:00:00","delivery_end":"21:00:00","timezone":"Europe/Istanbul"}"""
            bodies["/api/settings/branding"] = """{"caption_template":"Eski","intro_asset":null,"intro_duration":null,"logo_asset":"logo.png","outro_asset":null,"outro_duration":null}"""
            bodies["/api/setup/consent"] = """{"accepted_at":null,"text":"Politika metni","version":1}"""
            bodies["/api/setup/consent/accept"] = """{"accepted_at":"2026-10-05T12:00:00Z","version":1}"""
            bodies["/api/meta/status"] = """{"health":"not_connected"}"""
            bodies["/api/packages/active/editor"] = editorJson()
            bodies["/api/packages/active/order"] = "{}"
            bodies["/api/packages/active/selections"] = "{}"
            server.dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    seen.add("${request.method} ${request.path}")
                    if (request.path == "/api/events") return MockResponse().setHeader("Content-Type", "text/event-stream")
                        .setBody("event: ready\ndata: {\"protocol\":1}\n\n" + "event: heartbeat\ndata: {}\n\n".repeat(20_000))
                        .throttleBody(64, 100, TimeUnit.MILLISECONDS)
                    if (request.method == "PUT" && request.path == "/api/settings/reminders" && (codes[request.path] ?: 200) == 200) {
                        val input = kotlinx.serialization.json.Json.parseToJsonElement(request.body.clone().readUtf8()).jsonObject
                        bodies[request.path!!] = kotlinx.serialization.json.JsonObject(input +
                            ("timezone" to kotlinx.serialization.json.JsonPrimitive("Europe/Istanbul"))).toString()
                    }
                    return MockResponse().setResponseCode(codes[request.path] ?: 200)
                        .setBody(if (request.path == "/api/packages/active/edits") bodies.getValue("/api/packages/active/editor") else bodies[request.path] ?: "{}")
                        .also { if (request.path == delayPath) it.setBodyDelay(1, TimeUnit.SECONDS) }
                }
            }
            server.start()
            origin = server.url("/").toString().trimEnd('/')
            if (configure) store.setOrigin(origin)
            if (paired) store.saveToken(origin, "DEVICE")
            model = AppViewModel(store, OkHttpClient(), 1, true, saved, network = network, draftStore = DraftStore(dir.resolve("drafts"))) {
                stopped++
                tokenAtStop = store.readToken(origin)
            }
            model.setForeground(true)
            owner.put("model", model)
        }
        fun await(predicate: (AppUiState) -> Boolean) {
            repeat(500) {
                main.scheduler.runCurrent()
                val state = model.state.value
                val synchronizing = state.phase == Phase.READY && state.networkConnected && state.issue == null &&
                    state.livePhase in setOf(com.dojo.aisomedo.live.LivePhase.CONNECTING, com.dojo.aisomedo.live.LivePhase.SYNCING)
                if (predicate(state) && !synchronizing) return
                Thread.sleep(10)
            }
            fail("State did not arrive: ${model.state.value}")
        }
        fun recreate() {
            owner.clear()
            model = AppViewModel(store, OkHttpClient(), 1, true, saved, network = network, draftStore = DraftStore(dir.resolve("drafts")))
            model.setForeground(true)
            owner.put("model", model)
        }
        override fun close() { owner.clear(); server.shutdown(); dir.deleteRecursively() }
    }

    @Test fun completedDestinationReadsHistoryAndDetailWithoutMutatingActivePackage() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            assertFalse(f.seen.any { it == "GET /api/packages" })
            f.bodies["/api/packages"] = """[{"id":2,"folder_name":"finished","created_at":"2026-10-01T10:00:00Z","status":"completed"}]"""
            f.bodies["/api/packages/finished"] = """{"folder_name":"finished","caption":"Published caption","artifacts":[],"media":[],"order":[],"render_revision":null}"""
            f.model.navigate(Destination.entries.single { it.name == "COMPLETED" })
            f.await { !it.busy && f.seen.contains("GET /api/packages/finished") }
            assertEquals("COMPLETED", f.model.state.value.destination.name)
            assertEquals("COMPLETED", f.saved.get<String>("destination"))
            assertEquals("active", f.model.state.value.editor.snapshot?.`package`?.folderName)
            assertFalse(f.seen.any { it.startsWith("POST ") || it.startsWith("PUT ") || it.startsWith("DELETE ") })
        }
    }

    @Test fun futureOneoffReviewWaitsForExactOccurrenceThenOpensApprovalWithoutPublishing() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            val slot = com.dojo.aisomedo.api.DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 2)
            f.bodies["/api/dashboard/occurrences/2/decision"] = """{"occurrence_id":2,"due_at":"2026-10-05T12:00:00Z","status":"pending","package_folder":"active"}"""
            f.pendingDashboard(state = "preparing")
            f.model.decideOneoff(slot, skip = false)
            f.model.decideOneoff(slot, skip = false)
            f.await { !it.busy && it.oneoffDecision != null }
            assertNull(f.model.state.value.review.target)
            f.pendingDashboard(state = "review_ready", review = 8)
            val unrelated = kotlinx.serialization.json.Json.parseToJsonElement(f.bodies.getValue("/api/dashboard").replace("\"occurrence_id\":2", "\"occurrence_id\":9")).jsonObject["pending_actions"]!!.jsonArray.single()
            f.pendingDashboard(state = "preparing")
            val waiting = kotlinx.serialization.json.Json.parseToJsonElement(f.bodies.getValue("/api/dashboard")).jsonObject
            f.bodies["/api/dashboard"] = kotlinx.serialization.json.JsonObject(waiting + ("pending_actions" to kotlinx.serialization.json.JsonArray(waiting["pending_actions"]!!.jsonArray + unrelated))).toString()
            f.model.refresh()
            f.await { !it.busy }
            assertNull(f.model.state.value.review.target)
            f.bodies["/api/reviews/7"] = reviewJson()
            f.pendingDashboard(state = "review_ready", review = 7)
            f.model.refresh()
            f.await { it.review.detail?.review?.id == 7 && !it.review.busy }
            assertFalse(f.model.state.value.review.canApprove) // Preview still needs to load.
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val writes = requests.filter { it.method == "POST" }
            assertEquals(1, writes.size)
            assertEquals("/api/dashboard/occurrences/2/decision", writes.single().path)
            val body = kotlinx.serialization.json.Json.parseToJsonElement(writes.single().body.readUtf8()).jsonObject
            assertEquals("review", (body["action"] as kotlinx.serialization.json.JsonPrimitive).content)
            assertEquals(slot.dueAt, (body["expected_due_at"] as kotlinx.serialization.json.JsonPrimitive).content)
        }
    }

    @Test fun futureOneoffReviewDoesNotOpenForAReplacedPackage() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            val slot = com.dojo.aisomedo.api.DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 2)
            f.bodies["/api/dashboard/occurrences/2/decision"] = """{"occurrence_id":2,"due_at":"2026-10-05T12:00:00Z","status":"pending","package_folder":"active"}"""
            f.pendingDashboard(state = "preparing")
            f.model.decideOneoff(slot, skip = false)
            f.await { !it.busy && it.oneoffDecision != null }
            f.pendingDashboard(state = "review_ready", review = 7, folder = "replacement")
            f.model.refresh()
            f.await { !it.busy && it.oneoffDecision == null }
            assertNull(f.model.state.value.review.target)
            assertFalse(f.seen.contains("GET /api/reviews/7"))
        }
    }

    @Test fun futureOneoffReviewStopsWaitingWhenWorkerResolvesOccurrence() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            val slot = com.dojo.aisomedo.api.DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 2)
            f.pendingDashboard(state = "preparing")
            f.bodies["/api/dashboard/occurrences/2/decision"] = """{"occurrence_id":2,"due_at":"2026-10-05T12:00:00Z","status":"pending","package_folder":"active"}"""
            f.model.decideOneoff(slot, skip = false)
            f.await { !it.busy && it.oneoffDecision != null }
            f.pendingDashboard(includeOriginal = false)
            f.model.refresh()
            f.await { !it.busy }
            assertNull(f.model.state.value.oneoffDecision)
            assertEquals(ReviewIssue.ALREADY_HANDLED, f.model.state.value.oneoffDecisionIssue)
            assertNull(f.model.state.value.review.target)
        }
    }

    @Test fun navigationCancelsDelayedOneoffReviewContinuation() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            val slot = com.dojo.aisomedo.api.DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 2)
            f.pendingDashboard(state = "preparing")
            f.bodies["/api/dashboard/occurrences/2/decision"] = """{"occurrence_id":2,"due_at":"2026-10-05T12:00:00Z","status":"pending","package_folder":"active"}"""
            f.delayPath = "/api/dashboard/occurrences/2/decision"
            f.model.decideOneoff(slot, skip = false)
            f.await { f.seen.contains("POST /api/dashboard/occurrences/2/decision") }
            f.model.navigate(Destination.PACKAGE)
            f.model.navigate(Destination.DASHBOARD)
            f.await { !it.busy }
            assertNull(f.model.state.value.oneoffDecision)
            assertNull(f.model.state.value.review.target)
        }
    }

    @Test fun futureOneoffUncertainWriteCannotRepeatUntilExplicitRefresh() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            val slot = com.dojo.aisomedo.api.DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 2)
            f.codes["/api/dashboard/occurrences/2/decision"] = 502
            f.model.decideOneoff(slot, skip = false)
            f.await { !it.busy && it.issue != null }
            f.model.decideOneoff(slot, skip = false)
            main.scheduler.runCurrent()
            assertEquals(1, f.seen.count { it == "POST /api/dashboard/occurrences/2/decision" })
            assertNull(f.model.state.value.review.target)
        }
    }

    @Test fun futureOneoffSkipSendsConfirmationAndCannotRepeat() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            val slot = com.dojo.aisomedo.api.DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 2)
            f.bodies["/api/dashboard/occurrences/2/decision"] = """{"occurrence_id":2,"due_at":"2099-08-04T10:00:00+03:00","status":"skipped","package_folder":"active"}"""
            f.model.decideOneoff(slot, skip = true)
            f.await { !it.busy && it.oneoffDecision?.status == "skipped" }
            f.model.decideOneoff(slot, skip = true)
            main.scheduler.runCurrent()
            val writes = (0 until f.server.requestCount).map { f.server.takeRequest() }.filter { it.method == "POST" }
            assertEquals(1, writes.size)
            val body = kotlinx.serialization.json.Json.parseToJsonElement(writes.single().body.readUtf8()).jsonObject
            assertEquals("skip", (body["action"] as kotlinx.serialization.json.JsonPrimitive).content)
            assertEquals(true, (body["confirmed"] as kotlinx.serialization.json.JsonPrimitive).content.toBoolean())
            assertNull(f.model.state.value.review.target)
        }
    }

    @Test fun futureOneoffDateUsesPatchAndExpectedDateWithoutRegularLimit() {
        Fixture(paired = true).use { f ->
            f.await { it.canMutate }
            val slot = com.dojo.aisomedo.api.DashboardSlotOut("2099-08-04T10:00:00+03:00", "oneoff", 8)
            f.bodies["/api/dashboard/occurrences/8"] = """{"kind":"oneoff","due_at":"2099-08-05T12:30:00+03:00","occurrence_id":8}"""
            f.model.changeOneoffDate(slot, java.time.LocalDate.of(2099, 8, 5), java.time.LocalTime.of(12, 30))
            f.await { !it.busy }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val patch = requests.single { it.method == "PATCH" }
            assertEquals("/api/dashboard/occurrences/8", patch.path)
            val body = kotlinx.serialization.json.Json.parseToJsonElement(patch.body.readUtf8()).jsonObject
            assertEquals("2099-08-04T10:00:00+03:00", body["expected_due_at"]?.let { (it as kotlinx.serialization.json.JsonPrimitive).content })
            assertEquals("2099-08-05T12:30+03:00", body["new_due_at"]?.let { (it as kotlinx.serialization.json.JsonPrimitive).content })
        }
    }

    @Test fun cachedAuthorityCannotAdmitWithoutLiveSynchronization() {
        assertFalse(AppUiState(phase = Phase.READY, networkConnected = true, authoritative = true).canMutate)
    }

    @Test fun editorReopenPreservesIncompleteDraftWithoutSubmitting() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "")))
            f.await { !it.editor.persisting }
            f.recreate()
            f.await { it.canEditMedia }
            assertEquals("", f.model.state.value.editor.inputs.getValue("a")[0].end)
            assertEquals(0, f.seen.count { it.startsWith("PUT /api/packages") })
        }
    }

    @Test fun saveOneMediaIgnoresInvalidSiblingAndSendsExactlyOneGroup() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5")))
            f.model.editRanges("c", listOf(RangeInput("0", "")))
            f.await { !it.editor.persisting }
            f.bodies["/api/packages/active/editor"] = editorJson(selections = "\"a\":[{\"start\":0,\"end\":5}],\"c\":[{\"start\":1,\"end\":3},{\"start\":7,\"end\":9}]")
            f.model.saveMedia("a"); f.await { !it.busy && !it.editor.isDirty("a") }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val body = kotlinx.serialization.json.Json.parseToJsonElement(requests.single { it.path == "/api/packages/active/edits" }.body.readUtf8()).jsonObject
            assertEquals(listOf("\"video:a\""), body.getValue("changes").jsonArray.map { it.jsonObject.getValue("key").toString() })
            assertEquals("", f.model.state.value.editor.inputs.getValue("c")[0].end)
            f.model.discardMedia("a")
            assertTrue(f.model.state.value.editor.isDirty("c"))
        }
    }

    @Test fun failedConfirmedRemovalPreservesDraftAndSuccessDiscardsOnlyTarget() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5")))
            f.model.editRanges("c", listOf(RangeInput("0", "2")))
            f.await { !it.editor.persisting }
            val path = "/api/packages/active/media/a/remove?expected_folder_name=active"
            f.codes[path] = 422
            f.model.removeMedia("a", confirmedDiscard = true); f.await { !it.busy }
            assertTrue(f.model.state.value.editor.isDirty("a")); assertTrue(f.model.state.value.editor.isDirty("c"))
            f.codes[path] = 200
            f.bodies["/api/packages/active/editor"] = editorJson(aStatus = "removed", order = "\"b\",\"c\"")
            f.model.removeMedia("a", confirmedDiscard = true); f.await { !it.busy }
            assertFalse(f.model.state.value.editor.isDirty("a")); assertTrue(f.model.state.value.editor.isDirty("c"))
        }
    }

    @Test fun clearRequiresConfirmationAndNeverRetriesAgainstReplacementPackage() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5"))); f.await { !it.editor.persisting }
            f.model.clearActivePackage(false); main.scheduler.runCurrent()
            assertFalse(f.seen.any { it == "POST /api/packages/active/clear" })
            f.codes["/api/packages/active/clear"] = 502
            f.model.clearActivePackage(true); f.await { !it.busy && it.editor.readRequired }
            assertTrue(f.model.state.value.editor.isDirty("a"))
            f.model.clearActivePackage(true); main.scheduler.runCurrent()
            assertEquals(1, f.seen.count { it == "POST /api/packages/active/clear" })
            f.bodies["/api/dashboard"] = f.bodies["/api/dashboard"]!!.replace("\"id\":1,\"folder_name\":\"active\"", "\"id\":2,\"folder_name\":\"replacement\"")
            f.bodies["/api/packages/active/editor"] = editorJson(folder = "replacement", id = 2)
            f.model.refresh(); f.await { !it.busy && it.editor.snapshot?.`package`?.id == 2 }
            f.model.refreshEditor(); f.await { !it.busy }
            f.model.clearActivePackage(true); f.await { !it.busy }
            val clears = (0 until f.server.requestCount).map { f.server.takeRequest() }.filter { it.path == "/api/packages/active/clear" }
            assertEquals(2, clears.size)
            assertTrue(clears.all { it.getHeader("If-Match") == "\"1:1\"" })
            assertTrue(clears.all { it.body.readUtf8().contains("\"expected_package_id\":1") })
        }
    }

    @Test fun photoSaveUsesSecondsAndRetainsOtherDraftAfterRecreation() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "")))
            f.model.editPhotoDuration("b", "4.5"); f.await { !it.editor.persisting }
            f.bodies["/api/packages/active/editor"] = editorJson().replace("\"effective_duration\":3", "\"effective_duration\":4.5")
            f.model.saveMedia("b"); f.await { !it.busy && !it.editor.isDirty("b") }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val changes = kotlinx.serialization.json.Json.parseToJsonElement(requests.single { it.path == "/api/packages/active/edits" }.body.readUtf8()).jsonObject.getValue("changes").jsonArray
            assertEquals(1, changes.size)
            assertEquals("\"photo:b\"", changes.single().jsonObject.getValue("key").toString())
            assertEquals("4.5", changes.single().jsonObject.getValue("proposed").jsonObject.getValue("seconds").toString())
            f.recreate(); f.await { it.canEditMedia }
            assertEquals("", f.model.state.value.editor.inputs.getValue("a")[0].end)
            assertFalse(f.model.state.value.editor.isDirty("b"))
        }
    }

    @Test fun renderAndRetrySendSavedIdentityNotDraftAndStaleRetryRefreshes() {
        Fixture(paired = true).use { f ->
            fun failedPreview() = editorJson().replaceFirst("\"preview_url\":null", "\"preview_url\":null,\"section_preview\":{\"status\":\"failed\",\"generation\":\"saved-generation\"}")
            f.bodies["/api/packages/active/editor"] = failedPreview()
            f.await { it.canEditMedia }; f.model.refreshEditor(); f.await { !it.busy }
            f.model.editRanges("a", listOf(RangeInput("0", ""))); f.await { !it.editor.persisting }
            f.bodies["/api/packages/active/render"] = """{"stale":true,"render_revision":"reel"}"""
            f.model.renderActivePackage(); f.await { !it.busy }
            f.bodies["/api/packages/active/media/a/sections/retry"] = failedPreview()
            f.model.retrySectionPreview("a"); f.await { !it.busy }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val retry = requests.single { it.path == "/api/packages/active/media/a/sections/retry" }
            assertEquals("""{"expected_folder_name":"active","expected_generation":"saved-generation","expected_package_id":1}""",
                kotlinx.serialization.json.Json.parseToJsonElement(retry.body.readUtf8()).toString())
            assertFalse(requests.any { it.path == "/api/packages/active/edits" })
            assertEquals("", f.model.state.value.editor.inputs.getValue("a")[0].end)
            f.codes["/api/packages/active/media/a/sections/retry"] = 409
            f.model.retrySectionPreview("a"); f.await { !it.busy }
            assertFalse(f.model.state.value.editor.readRequired)
        }
    }

    @Test fun successfulClearUsesCapturedRevisionAndDiscardsAcknowledgedDrafts() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5"))); f.await { !it.editor.persisting }
            f.bodies["/api/packages/active/clear"] = """{"folder_name":"active","upload_ids":[]}"""
            f.codes["/api/packages/active/editor"] = 404
            f.model.clearActivePackage(true); f.await { !it.busy && it.editor.snapshot == null }
            assertFalse(f.model.state.value.editor.dirty)
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val clear = requests.single { it.path == "/api/packages/active/clear" }
            assertEquals("\"1:1\"", clear.getHeader("If-Match"))
            assertEquals("""{"confirmed":true,"expected_folder_name":"active","expected_package_id":1}""", clear.body.readUtf8())
            assertNull(DraftStore(f.dir.resolve("drafts")).read(f.origin, f.model.currentBinding!!, 1))
        }
    }

    @Test fun cleanupRetryRemainsAvailableAfterAuthoritativeEditorDisappears() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5"))); f.await { !it.editor.persisting }
            f.codes["/api/packages/active/clear"] = 503
            f.model.clearActivePackage(true); f.await { !it.busy && it.editor.issue == EditorIssue.UNCERTAIN }
            f.codes["/api/packages/active/editor"] = 404
            f.model.refreshEditor(); f.await { !it.busy && it.editor.snapshot == null }
            f.codes["/api/packages/active/clear"] = 200
            f.bodies["/api/packages/active/clear"] = """{"folder_name":"active","upload_ids":[]}"""
            f.model.clearActivePackage(true); f.await { !it.busy && it.editor.storedDraft == null }
            val clears = (0 until f.server.requestCount).map { f.server.takeRequest() }.filter { it.path == "/api/packages/active/clear" }
            assertEquals(2, clears.size)
            assertTrue(clears.all { it.getHeader("If-Match") == "\"1:1\"" })
        }
    }

    @Test fun definitiveClearRejectionAllowsFreshExplicitConfirmationAfterRefresh() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.codes["/api/packages/active/clear"] = 409
            f.model.clearActivePackage(true); f.await { !it.busy && it.editor.readRequired }
            f.bodies["/api/packages/active/editor"] = editorJson().replace("\"content_revision\":1", "\"content_revision\":2")
            f.model.refreshEditor(); f.await { !it.busy && !it.editor.readRequired }
            f.model.clearActivePackage(true); f.await { !it.busy }
            val clears = (0 until f.server.requestCount).map { f.server.takeRequest() }.filter { it.path == "/api/packages/active/clear" }
            assertEquals(listOf("\"1:1\"", "\"1:2\""), clears.map { it.getHeader("If-Match") })
        }
    }

    @Test fun retryingCapturedOldCleanupNeverRebindsOrDiscardsReplacementDraft() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.bodies["/api/dashboard"] = f.bodies["/api/dashboard"]!!.replace("\"id\":1,\"folder_name\":\"active\"", "\"id\":2,\"folder_name\":\"replacement\"")
            f.bodies["/api/packages/active/editor"] = editorJson(folder = "replacement", id = 2)
            f.saved["clear_package_id"] = 1; f.saved["clear_package_folder"] = "active"
            f.saved["clear_package_revision"] = 1L; f.saved["clear_requires_read"] = true
            f.saved["clear_origin"] = f.origin; f.saved["clear_binding"] = f.model.currentBinding
            f.recreate(); f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", ""))); f.await { !it.editor.persisting }
            f.model.refreshEditor(); f.await { !it.busy }
            f.bodies["/api/packages/active/clear"] = """{"folder_name":"active","upload_ids":[]}"""
            f.model.clearActivePackage(true); f.await { !it.busy }
            assertEquals("", f.model.state.value.editor.inputs.getValue("a")[0].end)
            assertEquals(2, f.model.state.value.editor.draftPackageId)
            assertEquals("replacement", DraftStore(f.dir.resolve("drafts")).read(f.origin, f.model.currentBinding!!, 2)!!.folderName)
            assertNull(DraftStore(f.dir.resolve("drafts")).read(f.origin, f.model.currentBinding!!, 1))
        }
    }

    @Test fun lostRemovalReconcilesOnlyConfirmedTargetAfterRecreationWithoutReplay() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5")))
            f.model.editRanges("c", listOf(RangeInput("0", ""))); f.await { !it.editor.persisting }
            f.codes["/api/packages/active/media/a/remove?expected_folder_name=active"] = 502
            f.model.removeMedia("a", true); f.await { !it.busy && it.editor.issue == EditorIssue.UNCERTAIN }
            f.bodies["/api/packages/active/editor"] = editorJson(aStatus = "removed", order = "\"b\",\"c\"")
            f.recreate(); f.await { it.phase == Phase.READY && !it.busy }
            f.model.refreshEditor(); f.await { !it.busy }
            assertFalse(f.model.state.value.editor.isDirty("a"))
            assertTrue(f.model.state.value.editor.isDirty("c"))
            assertTrue(f.model.state.value.editor.conflicts.isEmpty())
            assertEquals(1, f.seen.count { it == "POST /api/packages/active/media/a/remove?expected_folder_name=active" })
        }
    }

    @Test fun capturedCleanupCannotCrossCredentialBindingOnRecreation() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.codes["/api/packages/active/clear"] = 503
            f.model.clearActivePackage(true); f.await { !it.busy && it.editor.issue == EditorIssue.UNCERTAIN }
            f.store.saveToken(f.origin, "REPLACEMENT")
            f.recreate(); f.await { it.canEditMedia }
            assertNull(f.saved.get<Int>("clear_package_id"))
            assertNull(f.model.state.value.pendingClearFolder)
            assertEquals(1, f.seen.count { it == "POST /api/packages/active/clear" })
        }
    }

    @Test fun lostGroupedSaveReconcilesOnReopenWithoutReplaying() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5")))
            f.await { it.editor.canSave }
            f.codes["/api/packages/active/edits"] = 502
            f.model.saveMedia("a")
            f.await { !it.busy && it.editor.issue == EditorIssue.UNCERTAIN }
            f.bodies["/api/packages/active/editor"] = editorJson(selections = "\"a\":[{\"start\":0,\"end\":5}]")
            f.recreate(); f.await { it.canEditMedia }
            assertFalse(f.model.state.value.editor.dirty)
            assertEquals(1, f.seen.count { it == "PUT /api/packages/active/edits" })
        }
    }

    @Test fun failedDraftReplacementBlocksSaveAndKeepsPreviousDurableInput() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5"))); f.await { !it.editor.persisting }
            val file = f.dir.resolve("drafts").walkTopDown().single { it.extension == "json" }
            val temporary = file.resolveSibling(file.nameWithoutExtension + ".tmp")
            temporary.mkdirs(); temporary.resolve("locked").writeText("fixture")
            f.model.editRanges("a", listOf(RangeInput("0", "8")))
            f.await { it.editor.persistenceIssue == DraftIssue.STORAGE }
            f.model.saveMedia("a"); main.scheduler.runCurrent()
            assertEquals(0, f.seen.count { it.startsWith("PUT /api/packages") })
            assertEquals("8", f.model.state.value.editor.inputs.getValue("a")[0].end)
            val binding = f.model.currentBinding!!
            assertEquals("5", DraftStore(f.dir.resolve("drafts")).read(f.origin, binding, 1)!!.inputs.getValue("a")[0].end)
            temporary.deleteRecursively()
            f.model.retryEditorPersistence(); f.await { !it.editor.persisting }
            assertNull(f.model.state.value.editor.persistenceIssue)
        }
    }

    @Test fun rolloverDiscardClearsOriginalDraftBeforeBindingReplacement() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5")))
            f.await { !it.editor.persisting }
            val binding = f.model.currentBinding!!
            val drafts = DraftStore(f.dir.resolve("drafts"))
            assertNotNull(drafts.read(f.origin, binding, 1))
            f.bodies["/api/dashboard"] = f.bodies["/api/dashboard"]!!.replace(
                "\"id\":1,\"folder_name\":\"active\"", "\"id\":2,\"folder_name\":\"replacement\"")
            f.bodies["/api/packages/active/editor"] = editorJson(folder = "replacement", id = 2)
            f.model.refresh()
            f.await { it.editor.snapshot?.`package`?.id == 2 }
            assertEquals(1, f.model.state.value.editor.draftPackageId)
            f.model.discardReplacedMediaDraft()
            f.await { it.canEditMedia && !it.editor.persisting }
            assertNull(drafts.read(f.origin, binding, 1))
            f.model.editRanges("a", listOf(RangeInput("1", "2")))
            f.await { !it.editor.persisting }
            assertEquals("2", drafts.read(f.origin, binding, 2)!!.inputs.getValue("a")[0].end)
        }
    }

    @Test fun replacementReadCannotResetOldDraftWhenDashboardLags() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5"))); f.await { !it.editor.persisting }
            f.bodies["/api/packages/active/editor"] = editorJson(folder = "replacement")
            f.model.refreshEditor(); f.await { !it.busy }
            assertEquals("5", f.model.state.value.editor.inputs.getValue("a")[0].end)
            assertNotNull(f.model.state.value.editor.storedDraft)
            assertFalse(f.model.state.value.canEditMedia)
        }
    }

    @Test fun foregroundStreamStopsAndDirectEditsStayLockedInBackground() {
        Fixture(paired = true).use { f ->
            f.await { it.canEditMedia }
            f.model.editRanges("a", listOf(RangeInput("0", "5")))
            val before = f.model.state.value.editor.inputs
            f.model.setForeground(false)
            f.await { !it.canMutate }
            val writes = f.seen.count { it.startsWith("POST") || it.startsWith("PUT") }
            f.model.editRanges("a", listOf(RangeInput("0", "8")))
            f.model.saveMedia("a")
            assertEquals(before, f.model.state.value.editor.inputs)
            assertEquals(writes, f.seen.count { it.startsWith("POST") || it.startsWith("PUT") })
        }
    }

    private fun reviewJson(id: Int = 7, status: String = "pending", version: Int = 3, revision: String = "exact", ready: Boolean = true) =
        """{"next_regular_at":"2099-10-19T10:00:00+03:00","preview_url":"/api/packages/active/render/preview?revision=$revision","render_ready":$ready,"review":{"caption":"Exact caption\n#dojo","created_at":"2026-10-11T10:00:00+03:00","id":$id,"occurrence_id":2,"package_folder":"active","revision_digest":"$revision","status":"$status","version":$version}}"""

    private fun Fixture.openPreparedReview() {
        await { it.phase == Phase.READY && !it.busy }
        bodies["/api/reviews/7"] = reviewJson()
        model.openReview(ReviewTarget(reviewId = 7))
        await { it.review.detail != null && !it.review.busy }
        model.markReviewPreviewReady(7, "exact", true)
        assertTrue(model.state.value.review.canApprove)
    }

    @Test fun brandingSelectionSurvivesReturnRefresh() = runTest(main.scheduler) {
        for (field in listOf("logo_asset", "intro_asset", "outro_asset")) Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.SETTINGS)
            f.await { it.canConfigure("logo") && it.canConfigure("cards") }
            f.bodies["/api/settings/branding/assets"] = """{"asset":"branding/assets/image.png","preview_url":"/api/settings/branding/assets/image.png"}"""
            f.bodies["/api/settings/branding"] = """{"caption_template":"Eski","intro_asset":null,"intro_duration":3,"logo_asset":null,"outro_asset":null,"outro_duration":3}"""
                .replace("\"$field\":null", "\"$field\":\"branding/assets/image.png\"")
            f.delayPath = "/api/compat"
            f.model.refresh()
            assertTrue(f.model.state.value.busy)
            f.model.uploadAsset(field, byteArrayOf(1, 2, 3))
            f.await { !it.busy }
            assertEquals(1, f.seen.count { it == "POST /api/settings/branding/assets" })
            val branding = f.model.state.value.branding!!
            assertEquals("branding/assets/image.png", when (field) {
                "intro_asset" -> branding.introAsset
                "outro_asset" -> branding.outroAsset
                else -> branding.logoAsset
            })
        }
    }

    @Test fun queuedBrandingSelectionCannotCrossSessionChange() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("logo")
            f.await { it.canConfigure("logo") }
            val binding = f.model.currentBinding
            f.model.refresh()
            f.model.uploadAsset("logo_asset", byteArrayOf(1), binding)
            f.model.changeServer()
            main.scheduler.runCurrent()
            assertEquals(Phase.ADDRESS, f.model.state.value.phase)
            assertTrue(f.seen.none { it == "POST /api/settings/branding/assets" })
        }
    }

    @Test fun queuedBrandingSelectionRequiresFreshConfiguration() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("logo")
            f.await { it.canConfigure("logo") }
            f.codes["/api/settings/branding"] = 503
            f.model.refresh()
            f.model.uploadAsset("logo_asset", byteArrayOf(1))
            f.await { !it.busy }
            assertFalse(f.model.state.value.canConfigure("logo"))
            assertTrue(f.seen.none { it == "POST /api/settings/branding/assets" })
        }
    }

    @Test fun preparedPreviewSurvivesSameRevisionRefresh() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.model.refreshReview(); f.await { !it.review.busy }
            assertTrue(f.model.state.value.review.canApprove)
            f.bodies["/api/reviews/7"] = reviewJson(revision = "new", ready = false)
            f.model.refreshReview(); f.await { !it.review.busy }
            assertFalse(f.model.state.value.review.canApprove)
            f.model.markReviewPreviewReady(7, "exact", true)
            assertFalse(f.model.state.value.review.canApprove)
        }
    }

    @Test fun oldTargetReadCannotReplaceNewReviewOrAuthorizeItsPreview() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.bodies["/api/reviews/7"] = reviewJson()
            f.bodies["/api/reviews/8"] = reviewJson(id = 8, revision = "other")
            f.delayPath = "/api/reviews/7"
            f.model.openReview(ReviewTarget(reviewId = 7))
            repeat(500) { main.scheduler.runCurrent(); if ("GET /api/reviews/7" !in f.seen) Thread.sleep(10) }
            f.model.openReview(ReviewTarget(reviewId = 8))
            f.await { it.review.detail?.review?.id == 8 && !it.review.busy }
            f.model.markReviewPreviewReady(7, "exact", true)
            assertFalse(f.model.state.value.review.canApprove)
            f.model.markReviewPreviewReady(8, "other", true)
            assertTrue(f.model.state.value.review.canApprove)
            assertEquals(8, f.model.state.value.review.detail!!.review.id)
        }
    }

    @Test fun explicitApprovePostsOnceWithDisplayedVersionAndReadsBackOutcome() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.bodies["/api/reviews/7/approve"] = """{"publication":{"status":"completed"}}"""
            f.bodies["/api/reviews/7"] = reviewJson(status = "approved", version = 4)
            f.model.approveReview(); f.model.approveReview()
            f.await { !it.review.busy }
            assertEquals(1, f.seen.count { it == "POST /api/reviews/7/approve" })
            assertEquals("approved", f.model.state.value.review.detail!!.review.status)
            assertEquals("completed", f.model.state.value.review.publication!!["status"]!!.toString().trim('"'))
            assertFalse(f.model.state.value.review.canApprove)
        }
    }

    @Test fun failedPublicationKeepsReviewAndEveryDecisionAvailable() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            val before = f.model.state.value.review.detail
            f.bodies["/api/reviews/7/approve"] = """{"publication":{"status":"failed","error":"bad video"}}"""
            f.model.approveReview(); f.await { !it.review.busy }
            assertEquals(before, f.model.state.value.review.detail)
            assertTrue(f.model.state.value.review.canApprove)
            assertTrue(f.model.state.value.review.canDecide)
            assertEquals(1, f.seen.count { it.startsWith("POST /api/reviews/") })
            f.model.requestReviewAction(ReviewAction.SKIP)
            assertEquals(ReviewAction.SKIP, f.model.state.value.review.target!!.action)
            f.model.requestReviewAction(ReviewAction.RESCHEDULE)
            assertEquals(ReviewAction.RESCHEDULE, f.model.state.value.review.target!!.action)
        }
    }

    @Test fun cardUploadAllowsDefaultDurationButRejectsFractionalDraft() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("cards")
            f.await { it.canConfigure("cards") }
            f.bodies["/api/settings/branding/assets"] = """{"asset":"branding/assets/card.mp4","preview_url":"/api/settings/branding/assets/card.mp4"}"""
            f.model.setDraft("intro_duration", "1.5", "cards")
            f.model.uploadAsset("intro_asset", byteArrayOf(1))
            assertEquals(UiIssue.INVALID_INPUT, f.model.state.value.issue)
            assertTrue(f.seen.none { it == "POST /api/settings/branding/assets" })
            f.model.setDraft("intro_duration", "", "cards")
            f.model.uploadAsset("intro_asset", byteArrayOf(1))
            f.await { !it.busy }
            assertEquals(1, f.seen.count { it == "POST /api/settings/branding/assets" })
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("""{"intro_asset":"branding/assets/card.mp4","intro_duration":null}""",
                requests.single { it.method == "PATCH" }.body.readUtf8())
        }
    }

    @Test fun clearingFailedCardSelectionDiscardsPendingInstallWithoutAWrite() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("cards")
            f.await { it.canConfigure("cards") }
            f.bodies["/api/settings/branding/assets"] = """{"asset":"branding/assets/card.mp4","preview_url":"/api/settings/branding/assets/card.mp4"}"""
            f.codes["/api/settings/branding"] = 422
            f.model.uploadAsset("intro_asset", byteArrayOf(1))
            f.await { !it.busy }
            assertTrue("intro_asset" in f.model.state.value.pendingAssets)
            val writes = f.seen.count { it.startsWith("PATCH ") }
            f.model.clearCard("intro_asset")
            assertFalse("intro_asset" in f.model.state.value.pendingAssets)
            assertNull(f.saved.get<String>("pending_intro_asset"))
            f.model.retryAsset("intro_asset")
            main.scheduler.runCurrent()
            assertEquals(writes, f.seen.count { it.startsWith("PATCH ") })
        }
    }

    @Test fun openingDecisionFormNeverPostsAndSkipRequiresItsForm() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.model.skipReview(); main.scheduler.runCurrent()
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
            f.model.requestReviewAction(ReviewAction.SKIP)
            main.scheduler.runCurrent()
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
            f.bodies["/api/reviews/7/skip"] = "{}"
            f.bodies["/api/reviews/7"] = reviewJson(status = "skipped", version = 4)
            f.model.skipReview(); f.await { !it.review.busy }
            assertEquals(1, f.seen.count { it == "POST /api/reviews/7/skip" })
        }
    }

    @Test fun conflictReadsBackHandledVersusStaleAndNeverAutomaticallyRepeats() = runTest(main.scheduler) {
        for (handled in listOf(false, true)) Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.codes["/api/reviews/7/approve"] = 409
            if (handled) f.bodies["/api/reviews/7"] = reviewJson(status = "skipped", version = 4)
            f.model.approveReview(); f.await { !it.review.busy }
            assertEquals(if (handled) ReviewIssue.ALREADY_HANDLED else ReviewIssue.STALE, f.model.state.value.review.issue)
            assertTrue(f.model.state.value.review.readRequired)
            f.model.approveReview(); main.scheduler.runCurrent()
            assertEquals(1, f.seen.count { it == "POST /api/reviews/7/approve" })
        }
    }

    @Test fun ambiguousMutationRequiresExplicitReadBeforeRetry() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.bodies["/api/reviews/7/approve"] = "[]"
            f.model.approveReview(); f.await { !it.review.busy }
            assertEquals(ReviewIssue.UNCERTAIN, f.model.state.value.review.issue)
            assertTrue(f.model.state.value.review.readRequired)
            f.model.approveReview(); main.scheduler.runCurrent()
            assertEquals(1, f.seen.count { it == "POST /api/reviews/7/approve" })
            f.model.refreshReview(); f.await { !it.review.busy }
            assertFalse(f.model.state.value.review.readRequired)
            assertTrue(f.model.state.value.review.canApprove)
        }
    }

    @Test fun reviewReadFailuresRespectMissingAuthAndVersionGates() = runTest(main.scheduler) {
        for (code in listOf(404, 401, 426, 503)) Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.codes["/api/reviews/7"] = code
            f.model.openReview(ReviewTarget(reviewId = 7))
            f.await { !it.review.busy && !it.busy }
            when (code) {
                401 -> { assertEquals(Phase.PAIRING, f.model.state.value.phase); assertNull(f.store.readToken(f.origin)) }
                426 -> assertEquals(Phase.UPDATE_REQUIRED, f.model.state.value.phase)
                404 -> assertEquals(ReviewIssue.NOT_FOUND, f.model.state.value.review.issue)
                503 -> assertEquals(ReviewIssue.NETWORK, f.model.state.value.review.issue)
            }
            assertFalse(f.model.state.value.review.canApprove)
        }
    }

    @Test fun oldSessionOrClosedReviewCannotApplyDelayedRead() = runTest(main.scheduler) {
        for (switchServer in listOf(false, true)) Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.bodies["/api/reviews/7"] = reviewJson()
            f.delayPath = "/api/reviews/7"
            f.model.openReview(ReviewTarget(reviewId = 7)); main.scheduler.runCurrent()
            if (switchServer) f.model.changeServer() else f.model.closeReview()
            repeat(120) { main.scheduler.runCurrent(); Thread.sleep(10) }
            assertNull(f.model.state.value.review.target)
            assertNull(f.model.state.value.review.detail)
            assertFalse(f.model.state.value.review.canApprove)
        }
    }

    @Test fun notificationVersionOrPackageMismatchCannotAuthorizeAnotherReview() = runTest(main.scheduler) {
        for (target in listOf(ReviewTarget(reviewId = 7, packageFolder = "old", expectedVersion = 3),
            ReviewTarget(reviewId = 7, packageFolder = "active", expectedVersion = 2))) {
            Fixture(paired = true).use { f ->
                f.await { it.phase == Phase.READY && !it.busy }
                f.bodies["/api/reviews/7"] = reviewJson()
                f.model.openReview(target); f.await { !it.review.busy }
                assertEquals(ReviewIssue.STALE, f.model.state.value.review.issue)
                f.model.markReviewPreviewReady(7, "exact", true)
                assertFalse(f.model.state.value.review.canApprove)
            }
        }
    }

    @Test fun recreationReloadsDurableInboxAndSavedTargetWithoutSubmitting() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.model.requestReviewAction(ReviewAction.RESCHEDULE)
            f.recreate()
            f.await { it.phase == Phase.READY && !it.busy && it.review.detail != null && !it.review.busy }
            assertEquals(ReviewAction.RESCHEDULE, f.model.state.value.review.target!!.action)
            assertFalse(f.model.state.value.review.canApprove)
            assertTrue(f.seen.count { it == "GET /api/dashboard" } >= 2)
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
            assertTrue(f.saved.keys().none { it.contains("token") })
        }
    }

    @Test fun invalidRescheduleTimeCanBeCorrectedWithoutReopeningForm() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.model.requestReviewAction(ReviewAction.RESCHEDULE)
            f.model.rescheduleReview(java.time.LocalDate.of(2020, 1, 1), java.time.LocalTime.NOON)
            assertEquals(ReviewIssue.INVALID_TIME, f.model.state.value.review.issue)
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
            f.bodies["/api/reviews/7/reschedule"] = "{}"
            f.bodies["/api/reviews/7"] = reviewJson(status = "rescheduled", version = 4)
            f.model.rescheduleReview(java.time.LocalDate.of(2099, 10, 11), java.time.LocalTime.NOON)
            f.await { !it.review.busy }
            assertEquals(1, f.seen.count { it == "POST /api/reviews/7/reschedule" })
        }
    }

    @Test fun rotatedBindingCannotSubmitWithOldReviewCredentials() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.store.saveToken(f.origin, "REPLACEMENT_DEVICE")
            f.model.approveReview(); f.await { !it.review.busy }
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
            assertNull(f.model.state.value.review.detail)
            assertEquals("REPLACEMENT_DEVICE", f.store.readToken(f.origin))
        }
    }

    @Test fun rotatedBindingCannotAcceptOldDelayedReviewRead() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.bodies["/api/reviews/7"] = reviewJson()
            f.delayPath = "/api/reviews/7"
            f.model.openReview(ReviewTarget(reviewId = 7))
            repeat(500) { main.scheduler.runCurrent(); if ("GET /api/reviews/7" !in f.seen) Thread.sleep(10) }
            assertTrue("GET /api/reviews/7" in f.seen)
            f.store.saveToken(f.origin, "REPLACEMENT_DEVICE")
            f.await { !it.review.busy }
            assertNull(f.model.state.value.review.detail)
            assertEquals("REPLACEMENT_DEVICE", f.store.readToken(f.origin))
        }
    }

    @Test fun refreshingReplacementSessionDiscardsPreviouslyPreparedReview() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.store.saveToken(f.origin, "REPLACEMENT_DEVICE")
            f.model.refresh(); f.await { !it.busy }
            assertNull(f.model.state.value.review.target)
            assertFalse(f.model.state.value.review.canApprove)
            assertTrue(f.saved.keys().none { it.startsWith("review_") })
            assertEquals("REPLACEMENT_DEVICE", f.store.readToken(f.origin))
        }
    }

    @Test fun previewTransferRequiresExactIdentityAndDoesNotPreparePlayerByItself() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.bodies["/api/reviews/7"] = reviewJson()
            f.model.openReview(ReviewTarget(reviewId = 7)); f.await { !it.review.busy }
            val path = "/api/packages/active/render/preview?revision=exact"
            f.bodies[path] = "preview"
            val file = f.dir.resolve("private-review.mp4")
            val transfer = async { f.model.downloadReviewPreview(7, "exact", file) }
            f.await { transfer.isCompleted }
            transfer.await()
            assertEquals("preview", file.readText())
            assertFalse(f.model.state.value.review.canApprove)
            val rejected = async { runCatching { f.model.downloadReviewPreview(7, "old", file) } }
            f.await { rejected.isCompleted }
            assertTrue(rejected.await().isFailure)
            assertFalse(file.exists())
            assertEquals(1, f.seen.count { it == "GET $path" })
        }
    }

    @Test fun sessionSwitchRejectsPreviewAndDeletesOwnedFile() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            val path = "/api/packages/active/render/preview?revision=exact"
            f.bodies[path] = "preview"
            f.delayPath = path
            val file = f.dir.resolve("private-review.mp4")
            val transfer = async { runCatching { f.model.downloadReviewPreview(7, "exact", file) } }
            repeat(500) { main.scheduler.runCurrent(); if ("GET $path" !in f.seen) Thread.sleep(10) }
            assertTrue("GET $path" in f.seen)
            f.model.changeServer()
            f.await { transfer.isCompleted }
            assertTrue(transfer.await().isFailure)
            assertFalse(file.exists())
            assertFalse(f.model.state.value.review.canApprove)
        }
    }

    @Test fun previewDisposalRevokesReadinessEvenDuringUncertainMutation() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.bodies["/api/reviews/7/approve"] = "[]"
            f.model.approveReview(); f.await { !it.review.busy }
            f.model.markReviewPreviewReady(7, "exact", false)
            assertFalse(f.model.state.value.review.previewReady)
            f.model.refreshReview(); f.await { !it.review.busy }
            assertFalse(f.model.state.value.review.canApprove)
        }
    }

    @Test fun pollingDoesNotResolveUncertainCommandOrOverwriteActionDraft() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.model.requestReviewAction(ReviewAction.RESCHEDULE)
            f.model.refreshReviewOnInvalidation(); f.await { !it.review.busy }
            assertEquals(ReviewAction.RESCHEDULE, f.model.state.value.review.target!!.action)
            f.bodies["/api/reviews/7/approve"] = "[]"
            f.model.approveReview(); f.await { !it.review.busy }
            val reads = f.seen.count { it == "GET /api/reviews/7" }
            f.model.refreshReviewOnInvalidation(); main.scheduler.runCurrent()
            assertEquals(reads, f.seen.count { it == "GET /api/reviews/7" })
            assertTrue(f.model.state.value.review.readRequired)
        }
    }

    @Test fun notificationShortcutOpensFormWithoutPostingAndRejectsOldBinding() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.bodies["/api/reviews/7"] = reviewJson()
            val target = NotificationTarget("review_required", "active", 7, 3, action = ReviewAction.SKIP)
            f.model.openNotification(target, f.origin, "old")
            main.scheduler.runCurrent(); assertNull(f.model.state.value.review.target)
            f.model.openNotification(target, f.origin, f.store.readSession(f.origin)!!.bindingId)
            f.await { it.review.detail != null && !it.review.busy }
            assertEquals(ReviewAction.SKIP, f.model.state.value.review.target!!.action)
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
        }
    }
    @Test fun notificationDuringStartupRestoresAfterRecreationWithoutSubmitting() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/reviews/7"] = reviewJson()
            f.model.openNotification(NotificationTarget("review_required", "active", 7, 3, action = ReviewAction.RESCHEDULE), f.origin, f.store.readSession(f.origin)!!.bindingId)
            f.recreate()
            f.await { it.phase == Phase.READY && !it.busy && it.review.detail != null && !it.review.busy }
            assertEquals(ReviewAction.RESCHEDULE, f.model.state.value.review.target!!.action)
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
        }
    }
    @Test fun publicationLaunchShowsNamedActivityContextWithoutMutation() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.openNotification(NotificationTarget("publication_confirmed", "completed-folder"), f.origin, f.store.readSession(f.origin)!!.bindingId)
            f.await { !it.busy }
            assertEquals(Destination.ACTIVITY, f.model.state.value.destination)
            assertEquals("completed-folder", f.model.state.value.outcomePackage)
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
        }
    }
    @Test fun pushAuthAndVersionFailuresOnlyAffectCapturedCurrentBinding() = runTest(main.scheduler) {
        for (code in listOf(401, 426)) Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            val binding = f.store.readSession(f.origin)!!.bindingId
            f.model.observePushFailure(PushFailure(f.origin, "old", code))
            assertEquals(Phase.READY, f.model.state.value.phase)
            f.model.observePushFailure(PushFailure("https://other.example", binding, code))
            assertEquals(Phase.READY, f.model.state.value.phase)
            f.model.observePushFailure(PushFailure(f.origin, binding, code))
            f.await { it.phase == (if (code == 401) Phase.PAIRING else Phase.UPDATE_REQUIRED) && !it.busy }
            assertEquals(if (code == 401) Phase.PAIRING else Phase.UPDATE_REQUIRED, f.model.state.value.phase)
        }
    }

    private fun Fixture.pendingDashboard(state: String = "empty_package", review: Int? = null, folder: String = "active", includeOriginal: Boolean = true) {
        val base = kotlinx.serialization.json.Json.parseToJsonElement(bodies["/api/dashboard"]!!).jsonObject
        val pkg = kotlinx.serialization.json.Json.parseToJsonElement(editorJson(folder = folder)).jsonObject["package"]!!
        val original = """{"due_at":"2026-08-03T10:00:00+03:00","occurrence_id":2,"package_folder":"$folder","review_id":${review ?: "null"},"state":"$state","version":${if (review != null) 3 else "null"}}"""
        val actions = kotlinx.serialization.json.Json.parseToJsonElement(if (includeOriginal) "[$original]" else "[]")
        bodies["/api/dashboard"] = kotlinx.serialization.json.JsonObject(base + mapOf("package" to pkg, "pending_actions" to actions)).toString()
    }
    private fun Fixture.openEmptyContinuation() {
        await { it.phase == Phase.READY && !it.busy }
        pendingDashboard()
        bodies["/api/packages/active/render"] = """{"render_revision":"exact","stale":true}"""
        model.openReview(ReviewTarget(occurrenceId = 2, packageFolder = "active", action = ReviewAction.UPLOAD))
        await { !it.review.busy && !it.busy }
    }
    private fun Fixture.uploadRow(phase: UploadPhase, binding: String = store.readSession(origin)!!.bindingId) =
        UploadRecord("synthetic", origin, binding, "content://synthetic/clip", "clip.mp4", "video/mp4", 1, phase = phase)

    @Test fun continuationSelectionRejectsStaleTargetAndReplacementDuringPicker() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            val packageId = f.model.reviewUploadPackageId!!
            var selections = 0
            f.pendingDashboard(folder = "replacement")
            f.model.enqueueReviewUploads(packageId) { selections++ }
            f.await { !it.review.busy }
            assertEquals(0, selections)
            assertNull(f.model.reviewUploadPackageId)
            f.model.enqueueReviewUploads(packageId) { selections++ }
            main.scheduler.runCurrent()
            assertEquals(0, selections)
        }
    }
    @Test fun preparingHistoricalReviewDoesNotStealContinuationFromReadySuccessor() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            f.pendingDashboard("preparing", 7)
            f.bodies["/api/reviews/7"] = reviewJson(ready = false)
            f.model.refreshReview(); f.await { !it.review.busy }
            assertNull(f.model.state.value.review.target!!.reviewId)
            assertEquals(ReviewAction.UPLOAD, f.model.state.value.review.target!!.action)
            f.pendingDashboard("review_ready", 8)
            val dashboard = kotlinx.serialization.json.Json.parseToJsonElement(f.bodies["/api/dashboard"]!!).jsonObject
            val old = kotlinx.serialization.json.Json.parseToJsonElement("""{"due_at":"now","occurrence_id":2,"package_folder":"active","review_id":7,"state":"preparing","version":3}""")
            f.bodies["/api/dashboard"] = kotlinx.serialization.json.JsonObject(dashboard + ("pending_actions" to kotlinx.serialization.json.JsonArray(listOf(old) + dashboard["pending_actions"]!!.jsonArray))).toString()
            f.bodies["/api/reviews/8"] = reviewJson(id = 8)
            f.model.refreshReview(); f.await { !it.review.busy }
            assertEquals(8, f.model.state.value.review.target!!.reviewId)
            assertTrue(f.seen.none { it == "POST /api/packages/active/render" })
        }
    }
    @Test fun failedGlobalRefreshBlocksAllReviewMutationsUntilRecovery() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openPreparedReview()
            f.codes["/api/compat"] = 503
            f.model.refresh(); f.await { !it.busy }
            assertTrue(f.model.state.value.stale)
            f.model.approveReview()
            f.await { !it.review.busy }
            f.model.requestReviewAction(ReviewAction.SKIP); f.model.skipReview()
            f.await { !it.review.busy }
            f.model.requestReviewAction(ReviewAction.RESCHEDULE)
            f.model.rescheduleReview(java.time.LocalDate.of(2099, 10, 19), java.time.LocalTime.NOON)
            f.await { !it.review.busy }
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
            f.codes.remove("/api/compat")
            f.model.refresh(); f.await { !it.busy && !it.review.busy }
            assertFalse(f.model.state.value.stale)
        }
    }
    @Test fun conflictReadbackRefreshesHandledInboxWithoutReplay() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.pendingDashboard("review_ready", 7)
            f.openPreparedReview()
            f.codes["/api/reviews/7/approve"] = 409
            f.bodies["/api/reviews/7"] = reviewJson(status = "approved", version = 4)
            f.pendingDashboard(includeOriginal = false)
            f.model.approveReview(); f.await { !it.review.busy }
            assertEquals(ReviewIssue.ALREADY_HANDLED, f.model.state.value.review.issue)
            f.model.closeReview()
            assertTrue(f.model.state.value.dashboard!!.pendingActions.isEmpty())
            assertEquals(1, f.seen.count { it == "POST /api/reviews/7/approve" })
        }
    }
    @Test fun foregroundReceiptRefreshesInboxOnlyForCurrentSession() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.pendingDashboard("review_ready", 7)
            val binding = f.store.readSession(f.origin)!!.bindingId
            f.model.observePushReceipt(PushReceipt(f.origin, "old"))
            main.scheduler.runCurrent()
            assertTrue(f.model.state.value.dashboard!!.pendingActions.isEmpty())
            f.model.observePushReceipt(PushReceipt(f.origin, binding))
            f.await { !it.busy }
            assertEquals(7, f.model.state.value.dashboard!!.pendingActions.single().reviewId)
            assertTrue(f.seen.none { it.startsWith("POST /api/reviews") })
        }
    }
    @Test fun receiptDuringActiveRefreshQueuesAuthoritativeFollowup() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            val reads = f.seen.count { it == "GET /api/dashboard" }
            f.delayPath = "/api/dashboard"
            f.model.refresh()
            f.await { f.seen.count { path -> path == "GET /api/dashboard" } > reads }
            f.pendingDashboard("review_ready", 7)
            f.model.observePushReceipt(PushReceipt(f.origin, f.store.readSession(f.origin)!!.bindingId))
            f.delayPath = null
            f.await { !it.busy }
            assertEquals(7, f.model.state.value.dashboard!!.pendingActions.singleOrNull()?.reviewId)
            assertEquals(reads + 2, f.seen.count { it == "GET /api/dashboard" })
        }
    }
    @Test fun explicitSuccessfulRefreshAdvancesAuthoritativeDashboardEvenIfPayloadUnchanged() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            val first = f.model.state.value.dashboardRevision
            f.model.refresh(); f.await { !it.busy }
            assertEquals(first + 1, f.model.state.value.dashboardRevision)
            f.codes["/api/dashboard"] = 503
            f.model.refresh(); f.await { !it.busy }
            assertEquals(first + 1, f.model.state.value.dashboardRevision)
        }
    }

    @Test fun unresolvedLocalUploadsCannotRenderAndForeignSessionRowsDoNotBlock() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            for (phase in listOf(UploadPhase.QUEUED, UploadPhase.PROCESSING, UploadPhase.CONFLICT, UploadPhase.FAILED, UploadPhase.WAITING, UploadPhase.RETRYABLE)) {
                f.model.continueReview(listOf(f.uploadRow(phase)))
                main.scheduler.runCurrent()
                assertTrue(f.seen.none { it == "POST /api/packages/active/render" })
            }
            f.pendingDashboard("preparing")
            f.model.continueReview(listOf(f.uploadRow(UploadPhase.CONFLICT, "old-binding")))
            f.await { !it.review.busy }
            assertEquals(1, f.seen.count { it == "POST /api/packages/active/render" })
        }
    }
    @Test fun finalizedUploadsRenderOnceThenBindExactOccurrenceNotUnrelatedReview() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            assertEquals(Destination.PACKAGE, f.model.state.value.destination)
            f.pendingDashboard("preparing")
            f.model.continueReview(listOf(f.uploadRow(UploadPhase.FINALIZED)))
            f.await { !it.review.busy }
            assertTrue(f.model.state.value.review.continuing)
            f.model.continueReview(listOf(f.uploadRow(UploadPhase.FINALIZED)))
            main.scheduler.runCurrent()
            assertEquals(1, f.seen.count { it == "POST /api/packages/active/render" })
            f.pendingDashboard("review_ready", 7)
            val dashboard = kotlinx.serialization.json.Json.parseToJsonElement(f.bodies["/api/dashboard"]!!).jsonObject
            val other = kotlinx.serialization.json.Json.parseToJsonElement("""{"due_at":"now","occurrence_id":99,"package_folder":"active","review_id":8,"state":"review_ready","version":3}""")
            f.bodies["/api/dashboard"] = kotlinx.serialization.json.JsonObject(dashboard + ("pending_actions" to kotlinx.serialization.json.JsonArray(listOf(other) + dashboard["pending_actions"]!!.jsonArray))).toString()
            f.bodies["/api/reviews/7"] = reviewJson()
            f.model.refreshReview(); f.await { !it.review.busy }
            assertEquals(7, f.model.state.value.review.target!!.reviewId)
            assertEquals(2, f.model.state.value.review.detail!!.review.occurrenceId)
            assertFalse(f.model.state.value.review.previewReady)
            assertTrue(f.seen.none { it.contains("manual-publish") || it == "GET /api/reviews/8" })
            f.model.closeReview()
            assertEquals(Destination.DASHBOARD, f.model.state.value.destination)
        }
    }
    @Test fun workerFirstRenderAndReviewRequireNoRenderPost() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            f.pendingDashboard("review_ready", 7)
            f.bodies["/api/reviews/7"] = reviewJson()
            f.model.continueReview(emptyList()); f.await { !it.review.busy }
            assertEquals(7, f.model.state.value.review.target!!.reviewId)
            assertTrue(f.seen.none { it == "POST /api/packages/active/render" })
        }
    }
    @Test fun failedRenderNeedsExplicitRetryAndRecreationNeverReplaysIt() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            f.pendingDashboard("preparing")
            f.bodies["/api/packages/active/editor"] = editorJson().dropLast(1) + ",\"render_status\":\"failed\"}"
            f.model.continueReview(emptyList()); f.await { !it.review.busy }
            assertEquals(ReviewIssue.RENDER_FAILED, f.model.state.value.review.issue)
            assertTrue(f.seen.none { it == "POST /api/packages/active/render" })
            f.model.continueReview(emptyList(), retry = true); f.await { !it.review.busy }
            assertEquals(1, f.seen.count { it == "POST /api/packages/active/render" })
            f.recreate(); f.await { it.phase == Phase.READY && !it.review.busy && !it.busy }
            assertEquals(1, f.seen.count { it == "POST /api/packages/active/render" })
        }
    }
    @Test fun resolvedOrReplacedEmptyOccurrenceCannotRenderNewPackage() = runTest(main.scheduler) {
        for (resolved in listOf(false, true)) Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            if (resolved) f.pendingDashboard(includeOriginal = false) else f.pendingDashboard(folder = "replacement")
            f.model.continueReview(emptyList()); f.await { !it.review.busy }
            assertEquals(if (resolved) ReviewIssue.ALREADY_HANDLED else ReviewIssue.PACKAGE_CHANGED, f.model.state.value.review.issue)
            assertFalse(f.model.state.value.review.continuing)
            assertTrue(f.seen.none { it == "POST /api/packages/active/render" })
        }
    }
    @Test fun serverRejectingReplacementBetweenRenderTapAndResponseStopsContinuation() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation(); f.pendingDashboard("preparing")
            f.codes["/api/packages/active/render"] = 409
            f.model.continueReview(emptyList()); f.await { !it.review.busy }
            assertFalse(f.model.state.value.review.continuing)
            assertTrue(f.model.state.value.review.readRequired)
            assertEquals(ReviewIssue.PACKAGE_CHANGED, f.model.state.value.review.issue)
        }
    }
    @Test fun independentReviewAfterContinuationDoesNotInheritPreviousOccurrenceGuard() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.openEmptyContinuation()
            f.pendingDashboard("review_ready", 7)
            f.bodies["/api/reviews/7"] = reviewJson()
            f.model.refreshReview(); f.await { !it.review.busy }
            f.bodies["/api/reviews/8"] = reviewJson(id = 8).replace("\"occurrence_id\":2", "\"occurrence_id\":99")
            f.model.openReview(ReviewTarget(reviewId = 8)); f.await { !it.review.busy }
            assertEquals(8, f.model.state.value.review.detail?.review?.id)
            assertNull(f.model.state.value.review.issue)
            assertFalse(f.model.state.value.review.continuing)
        }
    }

    @Test fun openingPackageReadsEditorWithoutCreatingPackage() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE)
            repeat(30) { main.scheduler.runCurrent(); Thread.sleep(10) }
            assertTrue("Package screen must load authoritative editor", "GET /api/packages/active/editor" in f.seen)
            assertTrue(f.seen.none { it.startsWith("POST /api/packages") })
        }
    }

    @Test fun settingsLoadsConfigurationWithoutOpeningOnboardingAndRestoresDestination() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/setup"] = """{"checklist":[],"ready":true}"""
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.SETTINGS); f.await { !it.busy }
            assertNull(f.model.state.value.step)
            assertEquals("60", f.model.state.value.drafts["reminder_interval"])
            assertEquals("09:00:00", f.model.state.value.drafts["reminder_start"])
            assertTrue(f.model.state.value.canConfigure("reminders"))
            f.model.setDraft("reminder_interval", "90", "reminders")
            f.recreate(); f.await { it.phase == Phase.READY && !it.busy }
            assertEquals(Destination.SETTINGS, f.model.state.value.destination)
            assertNull(f.model.state.value.step)
            assertEquals("90", f.model.state.value.drafts["reminder_interval"])
            assertTrue(f.model.state.value.canConfigure("reminders"))
        }
    }

    @Test fun noOriginRequiresAddressWithoutNetwork() = runTest(main.scheduler) {
        Fixture(configure = false).use { f -> f.await { it.phase == Phase.ADDRESS }; assertEquals(0, f.server.requestCount) }
    }
    @Test fun reminderSavePersistsOvernightWindowAndReloadsAfterRecreation() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.SETTINGS); f.await { !it.busy }
            f.model.setDraft("reminder_interval", "90", "reminders")
            f.model.saveReminders("90", "21:00", "09:00"); f.await { !it.busy }
            assertEquals("90", f.model.state.value.drafts["reminder_interval"])
            assertEquals("21:00", f.model.state.value.drafts["reminder_start"])
            assertFalse("reminders" in f.model.state.value.dirtySteps)
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val put = requests.single { it.method == "PUT" }
            assertEquals("/api/settings/reminders", put.path)
            assertEquals("Bearer DEVICE", put.getHeader("Authorization"))
            assertEquals("Europe/Istanbul", f.model.state.value.reminders?.timezone)
            assertEquals(kotlinx.serialization.json.Json.parseToJsonElement("""{"interval_minutes":90,"delivery_start":"21:00","delivery_end":"09:00"}"""),
                kotlinx.serialization.json.Json.parseToJsonElement(put.body.readUtf8()))
            f.recreate(); f.await { it.phase == Phase.READY && !it.busy }
            assertEquals("90", f.model.state.value.drafts["reminder_interval"])
            assertEquals("21:00", f.model.state.value.drafts["reminder_start"])
        }
    }
    @Test fun remindersRejectInvalidInputAndRetainDraftOnRejectedSave() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.SETTINGS); f.await { !it.busy }
            val count = f.server.requestCount
            for ((interval, start, end) in listOf(Triple("0", "09:00", "21:00"), Triple("1.5", "09:00", "21:00"),
                Triple("2147483648", "09:00", "21:00"), Triple("60", "24:00", "21:00"), Triple("60", "09:00", "09:00"))) {
                f.model.saveReminders(interval, start, end)
                assertEquals(UiIssue.INVALID_INPUT, f.model.state.value.issue)
            }
            main.scheduler.runCurrent(); assertEquals(count, f.server.requestCount)
            f.model.setDraft("reminder_interval", "90", "reminders")
            f.codes["/api/settings/reminders"] = 422
            f.model.saveReminders("90", "09:00", "21:00"); f.await { !it.busy }
            assertEquals(UiIssue.INVALID_INPUT, f.model.state.value.issue)
            assertEquals("90", f.model.state.value.drafts["reminder_interval"])
            assertTrue("reminders" in f.model.state.value.dirtySteps)
        }
    }
    @Test fun reminderIntervalOnlyEditPreservesSecondBearingWindow() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.bodies["/api/settings/reminders"] = """{"interval_minutes":60,"delivery_start":"09:00:10","delivery_end":"09:00:50","timezone":"Europe/Istanbul"}"""
            f.model.navigate(Destination.SETTINGS); f.await { !it.busy }
            assertEquals("09:00:10", f.model.state.value.drafts["reminder_start"])
            assertEquals("09:00:50", f.model.state.value.drafts["reminder_end"])
            f.model.setDraft("reminder_interval", "90", "reminders")
            f.model.saveReminders("90", f.model.state.value.drafts["reminder_start"]!!, f.model.state.value.drafts["reminder_end"]!!)
            f.await { !it.busy }
            assertEquals(90, f.model.state.value.reminders?.intervalMinutes)
            assertEquals("09:00:10", f.model.state.value.reminders?.deliveryStart)
            assertEquals("09:00:50", f.model.state.value.reminders?.deliveryEnd)
            assertFalse("reminders" in f.model.state.value.dirtySteps)
        }
    }
    @Test fun reminderRefreshPreservesDirtyFieldsUntilExplicitReloadAndOfflineSaveNeverSends() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.SETTINGS); f.await { !it.busy }
            f.model.setDraft("reminder_interval", "90", "reminders")
            f.bodies["/api/settings/reminders"] = """{"interval_minutes":120,"delivery_start":"10:00:00","delivery_end":"22:00:00","timezone":"Europe/Istanbul"}"""
            f.model.refresh(); f.await { !it.busy }
            assertEquals("90", f.model.state.value.drafts["reminder_interval"])
            assertEquals("10:00:00", f.model.state.value.drafts["reminder_start"])
            assertTrue("reminders" in f.model.state.value.changedSteps)
            f.model.reloadStep("reminders"); f.await { !it.busy }
            assertEquals("120", f.model.state.value.drafts["reminder_interval"])
            val count = f.server.requestCount
            f.network.value = com.dojo.aisomedo.offline.NetworkStatus(false, 1)
            f.model.saveReminders("90", "09:00", "21:00")
            main.scheduler.runCurrent(); assertEquals(count, f.server.requestCount)
            assertFalse(f.model.state.value.canConfigure("reminders"))
        }
    }
    @Test fun packageOrderAndRemovalUseLoadedFolderAndReadBackAfterWrite() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE); f.await { it.editor.snapshot != null && !it.busy }
            f.bodies["/api/packages/active/editor"] = editorJson(order = "\"b\",\"c\",\"a\"")
            f.model.reorderMedia(listOf("b", "c", "a")); f.await { !it.busy }
            assertEquals(listOf("b", "c", "a"), f.model.state.value.editor.snapshot!!.montage.order)
            f.bodies["/api/packages/active/editor"] = editorJson(order = "\"b\",\"c\"", aStatus = "removed")
            f.model.removeMedia("a"); f.await { !it.busy }
            assertEquals("removed", f.model.state.value.editor.snapshot!!.media.first().status)
            assertEquals(listOf("b", "c"), f.model.state.value.editor.snapshot!!.montage.order)
            f.bodies["/api/packages/active/editor"] = editorJson()
            f.model.restoreMedia("a"); f.await { !it.busy }
            assertEquals("finalized", f.model.state.value.editor.snapshot!!.media.first().status)
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val put = requests.single { it.method == "PUT" }
            assertEquals("/api/packages/active/order", put.path)
            assertEquals(kotlinx.serialization.json.Json.parseToJsonElement("""{"order":["b","c","a"],"expected_folder_name":"active"}"""),
                kotlinx.serialization.json.Json.parseToJsonElement(put.body.readUtf8()))
            val post = requests.single { it.path?.contains("/remove?") == true }
            assertEquals("active", post.requestUrl!!.queryParameter("expected_folder_name"))
            assertEquals("/api/packages/active/media/a/remove?expected_folder_name=active", post.path)
            assertEquals("Bearer DEVICE", post.getHeader("Authorization"))
            assertEquals("/api/packages/active/media/a/restore?expected_folder_name=active", requests.single { it.path?.contains("/restore?") == true }.path)
        }
    }
    @Test fun trimSavePreservesOtherVideoSectionsAndInvalidDraftNeverTransfers() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE); f.await { it.editor.snapshot != null && !it.busy }
            val count = f.server.requestCount
            f.model.editRanges("a", listOf(RangeInput("", "3")))
            f.model.saveMedia("a"); main.scheduler.runCurrent()
            assertEquals(count, f.server.requestCount)
            f.model.editRanges("a", listOf(RangeInput("1", "3")))
            f.bodies["/api/packages/active/editor"] = editorJson(selections = "\"a\":[{\"start\":1,\"end\":3}],\"c\":[{\"start\":1,\"end\":3},{\"start\":7,\"end\":9}]")
            f.model.saveMedia("a"); f.await { !it.busy }
            assertFalse(f.model.state.value.editor.dirty)
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            val put = requests.single { it.method == "PUT" }
            val payload = kotlinx.serialization.json.Json.parseToJsonElement(put.body.readUtf8()).toString()
            assertTrue(payload.contains("\"expected_folder_name\":\"active\""))
            val changes = kotlinx.serialization.json.Json.parseToJsonElement(payload).jsonObject.getValue("changes").jsonArray
            assertEquals(1, changes.size)
            assertEquals("\"video:a\"", changes.single().jsonObject.getValue("key").toString())
            assertEquals(listOf(com.dojo.aisomedo.api.VideoRangeOut(start = 1.0, end = 3.0), com.dojo.aisomedo.api.VideoRangeOut(start = 7.0, end = 9.0)), f.model.state.value.editor.snapshot!!.montage.selections["c"])
        }
    }
    @Test fun failedPackageWriteRetainsDraftAndRequiresExplicitReadBeforeRetry() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE); f.await { it.editor.snapshot != null && !it.busy }
            f.model.editRanges("a", listOf(RangeInput("1", "3")))
            f.codes["/api/packages/active/edits"] = 500
            f.model.saveMedia("a"); f.await { !it.busy }
            assertTrue(f.model.state.value.editor.readRequired)
            assertEquals("1", f.model.state.value.editor.inputs["a"]!!.first().start)
            val count = f.server.requestCount
            f.model.saveMedia("a"); main.scheduler.runCurrent()
            assertEquals(count, f.server.requestCount)
            f.model.refreshEditor(); f.await { !it.busy }
            assertFalse(f.model.state.value.editor.readRequired)
            assertTrue(f.model.state.value.editor.dirty)
        }
    }
    @Test fun automaticRefreshPreservesConflictingBaselineUntilExplicitChoice() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE); f.await { it.editor.snapshot != null && !it.busy }
            f.model.editRanges("a", listOf(RangeInput("1", "3")))
            f.bodies["/api/packages/active/editor"] = editorJson(selections = "\"a\":[{\"start\":2,\"end\":4}]")
            f.model.refresh(); f.await { !it.busy }
            assertTrue(f.model.state.value.editor.readRequired)
            f.model.refreshEditor(); f.await { !it.busy }
            assertTrue(f.model.state.value.editor.readRequired)
            f.model.resolveMediaConflict("video:a", local = true); f.await { !it.editor.persisting }
            assertFalse(f.model.state.value.editor.readRequired)
            assertEquals("1", f.model.state.value.editor.inputs["a"]!!.first().start)
        }
    }
    @Test fun editorReadFailureBlocksWritesAndRevocationClearsEditor() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE); f.await { it.editor.snapshot != null && !it.busy }
            f.codes["/api/packages/active/editor"] = 503
            f.model.refreshEditor(); f.await { !it.busy }
            assertTrue(f.model.state.value.editor.readRequired)
            val count = f.server.requestCount
            f.model.removeMedia("a"); main.scheduler.runCurrent()
            assertEquals(count, f.server.requestCount)
            f.codes["/api/packages/active/editor"] = 401
            f.model.refreshEditor(); f.await { it.phase == Phase.PAIRING }
            f.await { !it.busy }
            assertNull(f.model.state.value.editor.snapshot)
            assertNull(f.store.readToken(f.origin))
        }
    }
    @Test fun orderingWithUnsavedRangesPreservesDraftAfterAcknowledgedReadBack() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE); f.await { it.editor.snapshot != null && !it.busy }
            f.model.editRanges("a", listOf(RangeInput("1", "3")))
            f.bodies["/api/packages/active/editor"] = editorJson(order = "\"b\",\"a\",\"c\"")
            f.model.reorderMedia(listOf("b", "a", "c")); f.await { !it.busy }
            assertFalse(f.model.state.value.editor.readRequired)
            assertTrue(f.model.state.value.editor.canSave)
            assertEquals("1", f.model.state.value.editor.inputs["a"]!!.first().start)
        }
    }
    @Test fun discardingDraftCannotBypassFailedWriteReadBackGuard() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.navigate(Destination.PACKAGE); f.await { it.editor.snapshot != null && !it.busy }
            f.model.editRanges("a", listOf(RangeInput("1", "3")))
            f.codes["/api/packages/active/editor"] = 503
            f.model.saveMedia("a"); f.await { !it.busy }
            assertTrue(f.model.state.value.editor.readRequired)
            f.model.discardMedia("a")
            assertTrue("Unverified read-only editor must retain draft", f.model.state.value.editor.dirty)
            val count = f.server.requestCount
            f.model.editRanges("c", listOf(RangeInput("2", "3")))
            f.model.saveMedia("a"); f.model.removeMedia("a"); main.scheduler.runCurrent()
            assertEquals("Discard must not authorize a write from unverified snapshot", count, f.server.requestCount)
            assertTrue(f.model.state.value.editor.readRequired)
            f.codes["/api/packages/active/editor"] = 200
            f.model.refreshEditor(); f.await { !it.busy }
            assertFalse(f.model.state.value.editor.readRequired)
        }
    }
    @Test fun backgroundAuthFailureReturnsToPairing() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.observeSessionFailure(UploadIssue.AUTH)
            f.await { it.phase == Phase.PAIRING && !it.busy }
            assertEquals(Phase.PAIRING, f.model.state.value.phase)
            assertNull(f.store.readToken(f.origin))
            assertEquals(1, f.stopped)
            assertEquals("DEVICE", f.tokenAtStop)
        }
    }
    @Test fun backgroundUpdateFailureGatesMutationWithoutDeletingCredential() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.observeSessionFailure(UploadIssue.UPDATE_REQUIRED)
            f.await { it.phase == Phase.UPDATE_REQUIRED }
            assertEquals(Phase.UPDATE_REQUIRED, f.model.state.value.phase)
            assertEquals("DEVICE", f.store.readToken(f.origin))
            assertEquals(1, f.stopped)
            val count = f.server.requestCount
            f.model.savePlan("2026-10-05", "18:30", true)
            main.scheduler.runCurrent()
            assertEquals(count, f.server.requestCount)
        }
    }
    @Test fun lateOldPairingCannotClearNewCredential() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.store.saveToken(f.origin, "NEW-DEVICE")
            f.model.observeSessionFailure(UploadIssue.AUTH)
            assertEquals("NEW-DEVICE", f.store.readToken(f.origin))
            assertEquals(0, f.stopped)
        }
    }
    @Test fun serverChangeStopsUploadsBeforeCredentialsChange() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.changeServer()
            assertEquals(1, f.stopped)
            assertEquals("DEVICE", f.tokenAtStop)
        }
    }
    @Test fun deliveredOldBackgroundIssueCannotClearRefreshedPairing() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            val old = f.store.readSession(f.origin)!!.bindingId
            f.store.saveToken(f.origin, "NEW-DEVICE")
            f.model.refresh(); f.await { it.phase == Phase.READY && !it.busy }
            f.model.observeSessionFailure(UploadIssue.AUTH, old)
            assertEquals(Phase.READY, f.model.state.value.phase)
            assertEquals("NEW-DEVICE", f.store.readToken(f.origin))
        }
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
            f.model.refresh(); f.await { it.phase == Phase.PAIRING && !it.busy }
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
    @Test fun oauthUsesExternalHttpsWithoutCredentialAndRequiresExplicitCandidate() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/meta/oauth/start"] = """{"attempt_id":"attempt-1","auth_url":"https://www.facebook.com/oauth?state=synthetic"}"""
            f.bodies["/api/meta/oauth/attempts/attempt-1"] = """{"id":"attempt-1","status":"completed","candidates":[{"ig_user_id":"one","ig_username":"dojo1"},{"ig_user_id":"two","ig_username":"dojo2"}]}"""
            f.bodies["/api/meta/oauth/attempts/attempt-1/select"] = """{"health":"healthy","ig_username":"dojo2"}"""
            f.await { it.phase == Phase.READY && !it.busy }
            val urls = mutableListOf<String>()
            f.model.startOAuth { urls.add(it) }; f.await { !it.busy }
            assertEquals(listOf("https://www.facebook.com/oauth?state=synthetic"), urls)
            assertEquals("attempt-1", f.model.saved.get<String>("oauth_attempt"))
            f.model.refresh(); f.await { !it.busy }
            assertEquals(2, f.model.state.value.attempt?.candidates?.size)
            val before = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("{}", before.single { it.path == "/api/meta/oauth/start" }.body.readUtf8())
            assertTrue(before.none { it.path?.endsWith("/select") == true })
            f.model.selectAccount("two"); f.await { !it.busy }
            val after = (0 until f.server.requestCount - before.size).map { f.server.takeRequest() }
            assertEquals("""{"ig_user_id":"two"}""", after.single { it.path?.endsWith("/select") == true }.body.readUtf8())
            assertNull(f.model.saved.get<String>("oauth_attempt"))
        }
    }
    @Test fun rejectedTokenPreservesPriorConnectionAndNoRawSecret() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/meta/status"] = """{"health":"healthy","ig_username":"dojo"}"""
            f.codes["/api/meta/instagram/token"] = 422
            f.bodies["/api/meta/instagram/token"] = """{"detail":"MANUAL-SECRET"}"""
            f.await { it.instagram != null && !it.busy }
            f.model.connectInstagramToken("MANUAL-SECRET"); f.await { !it.busy }
            assertEquals("dojo", f.model.state.value.instagram?.igUsername)
            assertEquals(UiIssue.INVALID_INPUT, f.model.state.value.issue)
            assertFalse(f.model.state.value.toString().contains("MANUAL-SECRET"))
            assertTrue(f.model.saved.keys().none { f.model.saved.get<Any>(it).toString().contains("MANUAL-SECRET") })
        }
    }
    @Test fun missingAttemptOffersRestartAndInvalidBrowserUrlNeverLaunches() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/meta/oauth/start"] = """{"attempt_id":"attempt-1","auth_url":"http://evil.example"}"""
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.startOAuth { fail("Unsafe browser URL") }; f.await { !it.busy }
            assertNull(f.model.saved.get<String>("oauth_attempt"))
            f.bodies["/api/meta/oauth/start"] = """{"attempt_id":"attempt-1","auth_url":"https://www.facebook.com/oauth"}"""
            f.codes["/api/meta/oauth/attempts/attempt-1"] = 404
            f.model.startOAuth {}; f.await { !it.busy }; f.model.checkOAuth(); f.await { !it.busy }
            assertEquals("unknown", f.model.state.value.attempt?.status)
        }
    }
    @Test fun uploadPatchFailureRetainsReferenceAndRetryDoesNotReupload() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/settings/branding/assets"] = """{"asset":"branding/assets/image.png","preview_url":"/api/settings/branding/assets/image.png"}"""
            f.await { it.phase == Phase.READY && !it.busy }
            f.codes["/api/settings/branding"] = 422
            f.model.uploadAsset("logo_asset", byteArrayOf(1, 2, 3)); f.await { !it.busy }
            assertEquals("branding/assets/image.png", f.model.state.value.pendingAssets["logo_asset"]?.asset)
            f.codes["/api/settings/branding"] = 200
            f.model.retryAsset("logo_asset"); f.await { !it.busy }
            assertTrue(f.model.state.value.pendingAssets.isEmpty())
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals(1, requests.count { it.method == "POST" && it.path == "/api/settings/branding/assets" })
            assertEquals(2, requests.count { it.method == "PATCH" })
            assertTrue(requests.none { it.method != "GET" && it.path?.startsWith("/api/packages") == true })
        }
    }
    @Test fun cardClearingUsesNullAndInvalidDurationsNeverSend() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/settings/branding"] = """{"caption_template":"Eski","intro_asset":"branding/assets/intro.png","intro_duration":1.0,"logo_asset":"logo.png","outro_asset":"branding/assets/outro.png","outro_duration":2.0}"""
            f.bodies["/api/setup/cards/skip"] = """{"checklist":[],"ready":true}"""
            f.await { it.phase == Phase.READY && !it.busy }
            val before = f.server.requestCount
            assertEquals("1", f.model.state.value.drafts["intro_duration"])
            listOf(Double.NaN, 0.0, -1.0, 1.5, Double.POSITIVE_INFINITY).forEach { f.model.saveCards("branding/assets/a.png", it, null, null) }
            assertEquals(before, f.server.requestCount)
            f.model.saveCards(null, null, null, null); f.await { !it.busy }
            f.model.skipCards(); f.await { !it.busy }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("""{"intro_asset":null,"intro_duration":null,"outro_asset":null,"outro_duration":null}""", requests.single { it.method == "PATCH" }.body.readUtf8())
            assertTrue(requests.any { it.path == "/api/setup/cards/skip" })
        }
    }
    @Test fun previewRevocationClearsSessionAndBlocksWizardWrites() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.codes["/api/settings/branding/assets/image.png"] = 401
            runCatching { f.model.preview("/api/settings/branding/assets/image.png") }
            assertEquals(Phase.PAIRING, f.model.state.value.phase)
            assertNull(f.store.readToken(f.origin))
            val before = f.server.requestCount
            f.model.saveCaption("Blocked"); main.scheduler.runCurrent()
            assertEquals(before, f.server.requestCount)
        }
    }
    @Test fun reopeningSessionRestoresSafeDraftAndNeverPairsAgain() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.setDraft("caption", "Rotation draft", "caption_template")
            f.model.navigate(Destination.SETTINGS)
            val saved = SavedStateHandle(f.model.saved.keys().associateWith { f.model.saved.get<Any>(it) })
            val owner = ViewModelStore()
            val reopened = AppViewModel(f.store, OkHttpClient(), 1, true, saved)
            owner.put("reopened", reopened)
            try {
                repeat(500) { main.scheduler.runCurrent(); if (reopened.state.value.phase != Phase.READY || reopened.state.value.busy) Thread.sleep(10) }
                assertEquals(Phase.READY, reopened.state.value.phase)
                assertEquals("Rotation draft", reopened.state.value.drafts["caption"])
                assertEquals(Destination.SETTINGS, reopened.state.value.destination)
                val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
                assertTrue(requests.none { it.path == "/api/pairing/validate" })
            } finally { owner.clear() }
        }
    }
    private fun settleDelayedResponse() {
        Thread.sleep(1100)
        repeat(50) { main.scheduler.runCurrent(); Thread.sleep(10) }
    }
    @Test fun preview426CannotBeOverwrittenByDelayedDashboard() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            val before = f.seen.count { it == "GET /api/dashboard" }
            f.delayPath = "/api/dashboard"
            f.codes["/api/settings/branding/assets/image.png"] = 426
            f.model.refresh()
            f.await { f.seen.count { it == "GET /api/dashboard" } > before }
            runCatching { f.model.preview("/api/settings/branding/assets/image.png") }
            settleDelayedResponse()
            assertEquals(Phase.UPDATE_REQUIRED, f.model.state.value.phase)
            assertFalse(f.model.state.value.busy)
            assertEquals("DEVICE", f.store.readToken(f.origin))
        }
    }
    @Test fun preview401CancelsUploadBeforeReferenceOrPatchCanReturn() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.bodies["/api/settings/branding/assets"] = """{"asset":"branding/assets/old.png","preview_url":"/api/settings/branding/assets/old.png"}"""
            f.delayPath = "/api/settings/branding/assets"
            f.codes["/api/settings/branding/assets/image.png"] = 401
            f.model.uploadAsset("logo_asset", byteArrayOf(1))
            f.await { "POST /api/settings/branding/assets" in f.seen }
            runCatching { f.model.preview("/api/settings/branding/assets/image.png") }
            settleDelayedResponse()
            assertEquals(Phase.PAIRING, f.model.state.value.phase)
            assertTrue(f.model.state.value.pendingAssets.isEmpty())
            assertTrue(f.model.saved.keys().none { it.startsWith("pending_") })
            assertFalse("PATCH /api/settings/branding" in f.seen)
        }
    }
    @Test fun mediaPreviewDownloadsFileAndSessionSwitchDeletesIt() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            val path = "/api/packages/active/media/a/preview"
            f.bodies[path] = "media-preview"
            val file = f.dir.resolve("media-preview.jpg")
            val transfer = async { f.model.downloadMediaPreview(path, file) }
            f.await { transfer.isCompleted }
            transfer.await()
            assertEquals("media-preview", file.readText())
            assertEquals(1, f.seen.count { it == "GET $path" })
            f.delayPath = path
            val stale = f.dir.resolve("media-stale.jpg")
            val rejected = async { runCatching { f.model.downloadMediaPreview(path, stale) } }
            repeat(500) { main.scheduler.runCurrent(); if ("GET $path" !in f.seen.drop(1)) Thread.sleep(10) }
            f.model.changeServer()
            f.await { rejected.isCompleted }
            assertTrue(rejected.await().isFailure)
            assertFalse(stale.exists())
        }
    }
    @Test fun captionEditMadeAfterSubmissionRemainsUnsavedAndVisible() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("caption_template"); f.await { !it.busy }
            f.model.setDraft("caption", "Submitted", "caption_template")
            f.bodies["/api/settings/branding"] = f.bodies["/api/settings/branding"]!!.replace("Eski", "Submitted")
            f.delayPath = "/api/settings/branding"
            f.model.saveCaption("Submitted")
            f.await { "PATCH /api/settings/branding" in f.seen }
            f.model.setDraft("caption", "New unsaved text", "caption_template")
            f.await { !it.busy }
            assertEquals("New unsaved text", f.model.state.value.drafts["caption"])
            assertTrue("caption_template" in f.model.state.value.dirtySteps)
        }
    }
    @Test fun leavingWizardDuringSaveDoesNotReopenIt() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.await { it.phase == Phase.READY && !it.busy }
            f.model.selectStep("caption_template"); f.await { !it.busy }
            f.bodies["/api/setup"] = """{"checklist":[{"key":"caption_template","label":"Caption","complete":true},{"key":"cards","label":"Cards","complete":false,"required":false}],"ready":true}"""
            f.delayPath = "/api/settings/branding"
            f.model.saveCaption("Submitted")
            f.await { "PATCH /api/settings/branding" in f.seen }
            f.model.navigate(Destination.SETTINGS)
            f.await { !it.busy }
            assertNull(f.model.state.value.step)
            assertEquals(Destination.SETTINGS, f.model.state.value.destination)
        }
    }
    @Test fun clearingOneCardDoesNotSendOtherCardCachedValues() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/settings/branding"] = """{"caption_template":"Eski","intro_asset":"branding/assets/intro.png","intro_duration":1.0,"logo_asset":"logo.png","outro_asset":"branding/assets/old-outro.png","outro_duration":2.0}"""
            f.await { it.branding?.introAsset != null && !it.busy }
            f.model.saveCards(null, null, "branding/assets/old-outro.png", 2.0)
            f.await { !it.busy }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("""{"intro_asset":null,"intro_duration":null}""", requests.single { it.method == "PATCH" }.body.readUtf8())
        }
    }
    @Test fun changingOneDurationDoesNotResendAssetOrUntouchedDuration() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/settings/branding"] = """{"caption_template":"Eski","intro_asset":"branding/assets/intro.png","intro_duration":1.0,"logo_asset":"logo.png","outro_asset":"branding/assets/old-outro.png","outro_duration":2.0}"""
            f.await { it.branding?.introAsset != null && !it.busy }
            f.model.saveCards("branding/assets/intro.png", 5.0, "branding/assets/old-outro.png", 2.0)
            f.await { !it.busy }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("""{"intro_duration":5.0}""", requests.single { it.method == "PATCH" }.body.readUtf8())
        }
    }
    @Test fun dirtyIntroDurationDoesNotFreezeOrOverwriteRemoteOutroDuration() = runTest(main.scheduler) {
        Fixture(paired = true).use { f ->
            f.bodies["/api/settings/branding"] = """{"caption_template":"Eski","intro_asset":"branding/assets/intro.png","intro_duration":1.0,"logo_asset":"logo.png","outro_asset":"branding/assets/outro.png","outro_duration":2.0}"""
            f.await { it.branding?.introAsset != null && !it.busy }
            f.model.setDraft("intro_duration", "5", "cards")
            f.bodies["/api/settings/branding"] = f.bodies["/api/settings/branding"]!!.replace("\"outro_duration\":2.0", "\"outro_duration\":7.0")
            f.model.refresh(); f.await { !it.busy }
            assertEquals("5", f.model.state.value.drafts["intro_duration"])
            assertEquals("7", f.model.state.value.drafts["outro_duration"])
            f.model.saveCards("branding/assets/intro.png", 5.0, "branding/assets/outro.png", f.model.state.value.drafts["outro_duration"]!!.toDouble())
            f.await { !it.busy }
            val requests = (0 until f.server.requestCount).map { f.server.takeRequest() }
            assertEquals("""{"intro_duration":5.0}""", requests.single { it.method == "PATCH" }.body.readUtf8())
        }
    }
}
