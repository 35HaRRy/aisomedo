package com.dojo.aisomedo.reviews

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.ui.DojoTheme
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class ReviewPreviewTest {
    @get:Rule val compose = createComposeRule()
    private val detail = ReviewDetailOut(null, "/api/packages/active/render/preview", true,
        ReviewOut("Caption", "2026-10-11T10:00:00+03:00", 7, null, 2, "active", "exact", "pending", 3))

    @Test fun nativePlayerPreparesExactPrivateClipAndDisposalRevokesReadiness() {
        val visible = mutableStateOf(true)
        val ready = AtomicBoolean(false)
        var file: File? = null
        compose.setContent { DojoTheme { if (visible.value) ReviewPreview(detail, { id, revision, output ->
            assertEquals(7, id); assertEquals("exact", revision)
            file = output
            InstrumentationRegistry.getInstrumentation().context.assets.open("synthetic-reel.mp4").use { input -> output.outputStream().use { input.copyTo(it) } }
        }, { _, _, value -> ready.set(value) }) } }
        compose.waitUntil(10000) { ready.get() }
        assertTrue(file!!.exists())
        compose.runOnIdle { visible.value = false }
        compose.waitUntil(5000) { !ready.get() && !file!!.exists() }
    }

    @Test fun undecodableVideoDeletesOwnedFileAndNeverClaimsPreparedPreview() {
        val ready = AtomicBoolean(false)
        var file: File? = null
        compose.setContent { DojoTheme { ReviewPreview(detail, { _, _, output ->
            file = output; output.writeText("not a Reel")
        }, { _, _, value -> ready.set(value) }) } }
        compose.waitUntil(10000) { compose.onAllNodesWithTag("review-preview-error").fetchSemanticsNodes().isNotEmpty() }
        assertFalse(ready.get())
        assertFalse(file!!.exists())
    }
}
