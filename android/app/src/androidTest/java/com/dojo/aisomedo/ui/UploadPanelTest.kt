package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.api.UploadOut
import com.dojo.aisomedo.uploads.*
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import kotlinx.serialization.json.*
import android.graphics.Bitmap
import com.dojo.aisomedo.api.ResolveConflictIn

class UploadPanelTest {
    @get:Rule val compose = createComposeRule()
    private fun row(phase: UploadPhase) = UploadRecord("00000000-0000-0000-0000-000000000033", "https://example.com", "a".repeat(64), "content://test/file", "Uzun dosya adı " .repeat(12) + ".mp4", "video/mp4", 1, 100,
        status = UploadOut(declaredSizeBytes = 100, receivedBytes = 100, receivedRanges = listOf(listOf(0, 100)), status = "processing", uploadId = "saved"),
        intent = if (phase == UploadPhase.PAUSED) UploadIntent.PAUSED else UploadIntent.ACTIVE, phase = phase)
    private fun show(phase: UploadPhase) = compose.setContent {
        DojoTheme { Column(Modifier.width(320.dp)) { UploadPanel(listOf(row(phase)), null, {}, {}, { _, _ -> }, { _, _ -> }, {}) } }
    }
    @Test fun pausedShowsResumeAndAccessibleProgress() {
        show(UploadPhase.PAUSED)
        compose.onNodeWithText("Devam et").assertExists()
        compose.onNodeWithText("Duraklat").assertDoesNotExist()
        compose.onNodeWithTag("upload-progress-${row(UploadPhase.PAUSED).id}").assert(SemanticsMatcher.keyIsDefined(SemanticsProperties.ProgressBarRangeInfo))
    }
    @Test fun processingIsNotFinalizedSuccess() {
        show(UploadPhase.PROCESSING)
        compose.onNodeWithText("Aktarım bitti; sunucuda işleniyor").assertExists()
        compose.onNodeWithText("Aktif Pakete eklendi").assertDoesNotExist()
    }
    @Test fun preparationDoesNotClaimUploadedPercentage() {
        show(UploadPhase.PREPARING)
        compose.onNodeWithText("Dosya doğrulanıyor; henüz aktarım değil").assertExists()
        compose.onNodeWithText("100 / 100 bayt · 100%").assertDoesNotExist()
    }
    @Test fun missingSourceAsksForOriginal() {
        show(UploadPhase.NEEDS_FILE)
        compose.onNodeWithText("Orijinal dosyayı seç").assertExists()
    }
    @Test fun conflictOffersAllDecisionsWithoutAutomaticOverwrite() {
        show(UploadPhase.CONFLICT)
        compose.onNodeWithText("İkisini de tut").assertExists()
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").assertExists()
        compose.onNodeWithText("Hedefi tut (yüklemeyi atla)").assertExists()
        compose.onNodeWithText("Tekrar dene").assertDoesNotExist()
        compose.onNodeWithText("Duraklat").assertDoesNotExist()
    }
    @Test fun overwriteWaitsForPreviewAndConsentThenSendsExactTarget() {
        val target = buildJsonObject {
            put("media_id", "target"); put("filename", "İstanbul.jpg"); put("size_bytes", 10)
            put("uploaded_at", "2026-10-09T10:00:00Z")
            put("processed", buildJsonObject { put("content_type", "image/jpeg") })
        }
        val row = row(UploadPhase.CONFLICT).let { it.copy(status = it.status!!.copy(status = "conflict", conflicts = listOf(target))) }
        var sent: ResolveConflictIn? = null
        compose.setContent {
            DojoTheme { Column(Modifier.width(320.dp).verticalScroll(rememberScrollState())) {
                UploadPanel(listOf(row), null, {}, {}, { _, _ -> }, { _, _ -> }, {},
                    onResolve = { _, body -> sent = body }, onPreview = { _, _, file ->
                        val bitmap = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
                        try { file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) } }
                        finally { bitmap.recycle() }
                    })
            } }
        }
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").performScrollTo().performClick()
        compose.onNodeWithText("Hedefin üzerine yaz").assertIsNotEnabled()
        compose.onNodeWithText("Bu işlem geri alınamaz. Hedef dosya kalıcı olarak değiştirilecek.").assertExists()
        compose.waitUntil(5000) { compose.onAllNodesWithContentDescription("Hedef önizlemesi: İstanbul.jpg").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Tüm uyumlu çakışmalara uygula").performScrollTo().performClick()
        compose.onNodeWithText("Kalıcı değişikliği onaylıyorum").performScrollTo().performClick()
        compose.onNodeWithText("Hedefin üzerine yaz").assertIsEnabled().performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals("keep_selected", sent!!.decision)
            assertEquals("target", sent!!.targetMediaId)
            assertTrue(sent!!.confirmedOverwrite)
            assertTrue(sent!!.applyToAll)
        }
    }
    @Test fun failedPreviewBlocksOverwriteButNotKeepBoth() {
        show(UploadPhase.CONFLICT)
        compose.onNodeWithText("Seçileni tut (hedefin üzerine yaz)").assertIsNotEnabled()
        compose.onNodeWithText("Kararı uygula").assertIsEnabled()
    }
    @Test fun retryableOffersExplicitRetry() {
        show(UploadPhase.RETRYABLE)
        compose.onNodeWithText("Tekrar dene").assertExists()
    }
    @Test fun longOperationAsksWithoutAutomaticallyPausing() {
        var pauses = 0
        val row = row(UploadPhase.PREPARING)
        val started = System.currentTimeMillis() - 61_000
        compose.setContent { DojoTheme {
            UploadPanel(listOf(row), null, {}, { pauses++ }, { _, _ -> }, { _, _ -> }, {},
                runningSinceMillis = mapOf(row.id to started))
        } }
        compose.waitUntil(5000) { compose.onAllNodesWithText("İşlem uzun sürüyor. Durdurulsun mu?").fetchSemanticsNodes().isNotEmpty() }
        compose.runOnIdle { assertEquals(0, pauses) }
        compose.onNodeWithText("Devam et").performClick()
        compose.onNodeWithText("İşlem uzun sürüyor. Durdurulsun mu?").assertDoesNotExist()
        compose.runOnIdle { assertEquals(0, pauses) }
    }
    @Test fun longOperationStopsOnlyAfterConfirmationAndClosesWhenFinished() {
        val row = row(UploadPhase.UPLOADING)
        val running = androidx.compose.runtime.mutableStateOf(mapOf(row.id to System.currentTimeMillis() - 61_000))
        val pauses = mutableListOf<String>()
        compose.setContent { DojoTheme {
            UploadPanel(listOf(row), null, {}, { pauses.add(it) }, { _, _ -> }, { _, _ -> }, {}, runningSinceMillis = running.value)
        } }
        compose.waitUntil(5000) { compose.onAllNodesWithText("Durdur").fetchSemanticsNodes().isNotEmpty() }
        compose.runOnIdle { assertTrue(pauses.isEmpty()) }
        compose.onNodeWithText("Durdur").performClick()
        compose.runOnIdle { assertEquals(listOf(row.id), pauses) }
        compose.onNodeWithText("İşlem uzun sürüyor. Durdurulsun mu?").assertDoesNotExist()
        compose.runOnIdle { running.value = mapOf(row.id to System.currentTimeMillis() - 62_000) }
        compose.waitUntil(5000) { compose.onAllNodesWithText("Durdur").fetchSemanticsNodes().isNotEmpty() }
        compose.runOnIdle { running.value = emptyMap() }
        compose.onNodeWithText("İşlem uzun sürüyor. Durdurulsun mu?").assertDoesNotExist()
        compose.runOnIdle { assertEquals(listOf(row.id), pauses) }
    }
    @Test fun uncertainInitializationCanBeStoppedButNotRetriedWhileRunning() {
        val row = row(UploadPhase.RETRYABLE).copy(status = null, issue = UploadIssue.NETWORK)
        var pauses = 0
        compose.setContent { DojoTheme {
            UploadPanel(listOf(row), null, {}, { pauses++ }, { _, _ -> }, { _, _ -> }, {},
                runningSinceMillis = mapOf(row.id to System.currentTimeMillis() - 61_000))
        } }
        compose.waitUntil(5000) { compose.onAllNodesWithText("Durdur").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Durdur").performClick()
        compose.onNodeWithText("Tekrar dene").assertIsNotEnabled()
        compose.runOnIdle { assertEquals(1, pauses) }
    }
    @Test fun offlineControlsDisabledExceptTransferPauseResume() {
        val active = row(UploadPhase.UPLOADING).copy(filename = "active", status = null)
        val paused = row(UploadPhase.PAUSED).copy(id = "paused", filename = "paused", status = null)
        val retry = row(UploadPhase.FAILED).copy(id = "retry", filename = "retry")
        compose.setContent { DojoTheme { Column(Modifier.verticalScroll(rememberScrollState())) {
            UploadPanel(listOf(active, paused, retry), null, {}, {}, { _, _ -> }, { _, _ -> }, {}, canMutate = false)
        } } }
        compose.onNodeWithText("Fotoğraf/video seç").assertIsNotEnabled()
        compose.onNodeWithText("Duraklat").assertIsEnabled()
        compose.onNodeWithText("Devam et").assertIsEnabled()
        compose.onNodeWithText("Tekrar dene").assertIsNotEnabled()
        compose.onAllNodesWithText("Listeden kaldır").assertAll(isNotEnabled())
    }
    @Test fun pickerSelectionSurvivesRefreshUntilAccessReturns() {
        val requests = mutableListOf<Int>()
        val registry = object : androidx.activity.result.ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: androidx.activity.result.contract.ActivityResultContract<I, O>, input: I, options: androidx.core.app.ActivityOptionsCompat?) { requests.add(requestCode) }
        }
        val owner = object : androidx.activity.result.ActivityResultRegistryOwner { override val activityResultRegistry = registry }
        val access = androidx.compose.runtime.mutableStateOf(true)
        val selected = mutableListOf<Pair<List<android.net.Uri>, Int?>>()
        val uri = android.net.Uri.parse("content://test/file")
        compose.setContent {
            androidx.compose.runtime.CompositionLocalProvider(androidx.activity.compose.LocalActivityResultRegistryOwner provides owner) {
                DojoTheme { UploadPanel(emptyList(), null, { fail("Generic upload callback") }, {}, { _, _ -> }, { _, _ -> }, {},
                    selectionPackageId = 42, onSelectPackage = { uris, id -> selected.add(uris to id) }, canMutate = access.value) }
            }
        }
        compose.onNodeWithText("Fotoğraf/video seç").performClick()
        compose.runOnIdle { access.value = false }
        compose.runOnIdle { registry.dispatchResult(requests.first(), listOf(uri)) }
        compose.runOnIdle {
            // Notification consent may also finish while the foreground refresh is busy.
            if (requests.size == 2) registry.dispatchResult(requests.last(), false)
            assertTrue(selected.isEmpty())
        }
        compose.runOnIdle { access.value = true }
        compose.runOnIdle { assertEquals(listOf(listOf(uri) to 42), selected) }
        compose.runOnIdle { access.value = false }
        compose.runOnIdle { access.value = true }
        compose.runOnIdle { assertEquals(1, selected.size) }
    }
    @Test fun pickerResultAfterDisconnectDoesNotInvokePackageMutation() {
        var launchedCode = 0
        val registry = object : androidx.activity.result.ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: androidx.activity.result.contract.ActivityResultContract<I, O>, input: I, options: androidx.core.app.ActivityOptionsCompat?) { launchedCode = requestCode }
        }
        val owner = object : androidx.activity.result.ActivityResultRegistryOwner { override val activityResultRegistry = registry }
        val access = androidx.compose.runtime.mutableStateOf(true)
        val context = androidx.compose.runtime.mutableStateOf<String?>("binding:epoch-1")
        var selections = 0
        compose.setContent {
            androidx.compose.runtime.CompositionLocalProvider(androidx.activity.compose.LocalActivityResultRegistryOwner provides owner) {
                DojoTheme { UploadPanel(emptyList(), null, { fail("Generic upload callback") }, {}, { _, _ -> }, { _, _ -> }, {},
                    selectionPackageId = 42, onSelectPackage = { _, _ -> selections++ }, canMutate = access.value, selectionContext = context.value) }
            }
        }
        compose.onNodeWithText("Fotoğraf/video seç").performClick()
        compose.runOnIdle { access.value = false; context.value = null }
        compose.runOnIdle { registry.dispatchResult(launchedCode, android.app.Activity.RESULT_OK, android.content.Intent().setData(android.net.Uri.parse("content://test/file"))) }
        compose.runOnIdle { assertEquals(0, selections) }
        compose.runOnIdle { access.value = true; context.value = "binding:epoch-2" }
        compose.runOnIdle { assertEquals(0, selections) }
    }
    @Test fun permissionResultAfterDisconnectDoesNotInvokePackageMutation() {
        val requests = mutableListOf<Int>()
        val registry = object : androidx.activity.result.ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: androidx.activity.result.contract.ActivityResultContract<I, O>, input: I, options: androidx.core.app.ActivityOptionsCompat?) { requests.add(requestCode) }
        }
        val owner = object : androidx.activity.result.ActivityResultRegistryOwner { override val activityResultRegistry = registry }
        val access = androidx.compose.runtime.mutableStateOf(true)
        val context = androidx.compose.runtime.mutableStateOf<String?>("binding:epoch-1")
        var selections = 0
        compose.setContent {
            androidx.compose.runtime.CompositionLocalProvider(androidx.activity.compose.LocalActivityResultRegistryOwner provides owner) {
                DojoTheme { UploadPanel(emptyList(), null, {}, {}, { _, _ -> }, { _, _ -> }, {},
                    selectionPackageId = 42, onSelectPackage = { _, _ -> selections++ }, canMutate = access.value, selectionContext = context.value) }
            }
        }
        compose.onNodeWithText("Fotoğraf/video seç").performClick()
        compose.runOnIdle { registry.dispatchResult(requests.first(), listOf(android.net.Uri.parse("content://test/file"))) }
        // Permission request only exists on API 33+ when notifications are not already granted.
        org.junit.Assume.assumeTrue(requests.size == 2)
        compose.runOnIdle { access.value = false; context.value = null }
        compose.runOnIdle { registry.dispatchResult(requests.last(), true) }
        compose.runOnIdle { assertEquals(0, selections) }
        compose.runOnIdle { access.value = true; context.value = "binding:epoch-2" }
        compose.runOnIdle { assertEquals(0, selections) }
    }
    @Test fun bufferedPickerSelectionCannotMoveToAnotherSession() {
        val requests = mutableListOf<Int>()
        val registry = object : androidx.activity.result.ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: androidx.activity.result.contract.ActivityResultContract<I, O>, input: I, options: androidx.core.app.ActivityOptionsCompat?) { requests.add(requestCode) }
        }
        val owner = object : androidx.activity.result.ActivityResultRegistryOwner { override val activityResultRegistry = registry }
        val access = androidx.compose.runtime.mutableStateOf(true)
        val context = androidx.compose.runtime.mutableStateOf<String?>("first-binding:epoch-1")
        var selections = 0
        compose.setContent {
            androidx.compose.runtime.CompositionLocalProvider(androidx.activity.compose.LocalActivityResultRegistryOwner provides owner) {
                DojoTheme { UploadPanel(emptyList(), null, {}, {}, { _, _ -> }, { _, _ -> }, {},
                    onSelectPackage = { _, _ -> selections++ }, canMutate = access.value, selectionContext = context.value) }
            }
        }
        compose.onNodeWithText("Fotoğraf/video seç").performClick()
        compose.runOnIdle { access.value = false }
        compose.runOnIdle { registry.dispatchResult(requests.first(), listOf(android.net.Uri.parse("content://test/file"))) }
        compose.runOnIdle { if (requests.size == 2) registry.dispatchResult(requests.last(), false) }
        compose.onNodeWithText("Dosyalar seçildi; yenileme tamamlanınca aktarım başlayacak.").assertExists()
        compose.runOnIdle { context.value = "second-binding:epoch-1"; access.value = true }
        compose.runOnIdle { assertEquals(0, selections) }
        compose.onNodeWithText("Dosyalar seçildi; yenileme tamamlanınca aktarım başlayacak.").assertDoesNotExist()
    }
}
