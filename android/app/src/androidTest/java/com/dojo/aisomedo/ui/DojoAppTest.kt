package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.runtime.mutableStateOf
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
    @Before fun setup() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                paths.add(request.method + " " + request.path)
                if (blocked) return MockResponse().setResponseCode(426).setBody("{}")
                val body = when (request.path) {
                    "/api/compat" -> """{"api_version":"0.1.0","android_min_version_code":1,"android_current_version_code":1,"update_url":"https://example.com/update"}"""
                    "/api/pairing/me" -> """{"id":1,"kind":"device","name":"Telefon","created_at":"2026-10-05T12:00:00Z","created_by":"cli","last_seen_at":null,"revoked_at":null}"""
                    "/api/setup" -> """{"checklist":[],"ready":true}"""
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
            model = AppViewModel(store, OkHttpClient(), 1, true, SavedStateHandle())
            owner.put("test", model)
        }
    }
    @After fun teardown() {
        InstrumentationRegistry.getInstrumentation().runOnMainSync { owner.clear() }
        server.shutdown()
    }
    @Test fun fourDestinationsAreDistinctAndPackageDoesNotCreate() {
        compose.setContent { DojoApp(model) {} }
        compose.waitUntil(10000) { model.state.value.phase == Phase.READY }
        compose.onNodeWithText("Bekleyen işlemler").assertExists()
        compose.onNodeWithText("Paket", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Henüz aktif paket yok").assertExists()
        compose.onNodeWithText("Hareketler", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Hareket geçmişi sonraki sürümde sunulacak.").assertExists()
        androidx.test.espresso.Espresso.pressBack()
        compose.onNodeWithText("Bekleyen işlemler").assertExists()
        compose.onNodeWithText("Ayarlar", useUnmergedTree = true).performClick()
        compose.onNodeWithText("Sunucuyu değiştir").performScrollTo().performClick()
        compose.onNodeWithText("Bu cihazın yeniden eşleştirilmesi gerekecek.").assertExists()
        compose.onNodeWithText("Vazgeç").performClick()
        Assert.assertTrue(paths.none { it.startsWith("POST /api/packages") })
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
        val dashboard = DashboardOut(time, DashboardInstagramOut("healthy", "dojo"), null, null,
            listOf("review_ready", "empty_package", "preparing").mapIndexed { i, state -> DashboardActionOut(time, i, null, null, state, null) },
            PlanOut(null, null, false, "Europe/Istanbul"), DashboardWorkerOut("busy", "healthy"))
        compose.setContent { DojoTheme { Column { DashboardScreen(dashboard, SetupOut(emptyList(), true), false, true, {}, {}) } } }
        listOf("İnceleme hazır", "Paket boş", "Hazırlanıyor", "dojo", "Çalışıyor", "Henüz aktif paket yok").forEach {
            compose.onNodeWithText(it).assertExists()
        }
        compose.onNodeWithText("Bilgiler henüz alınamadı. Tekrar deneyin.").assertDoesNotExist()
    }
}
