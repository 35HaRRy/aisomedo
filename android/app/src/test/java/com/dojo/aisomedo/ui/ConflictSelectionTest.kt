package com.dojo.aisomedo.ui

import com.dojo.aisomedo.uploads.*
import org.junit.Assert.*
import org.junit.Test
import kotlinx.serialization.json.*
import com.dojo.aisomedo.api.UploadOut

class ConflictSelectionTest {
    @Test fun overwriteNeedsLoadedPreviewAndExplicitConsent() {
        var choice = ConflictSelection(targetId = "target").choose("keep_selected")
        assertFalse(choice.canApply(false))
        choice = choice.preview(true)
        assertFalse(choice.canApply(false))
        choice = choice.copy(confirmed = true)
        assertTrue(choice.canApply(false))
        assertFalse(choice.canApply(true))
        val body = choice.body()
        assertEquals("target", body.targetMediaId)
        assertTrue(body.confirmedOverwrite)
        assertFalse(choice.target("other").confirmed)
        assertFalse(choice.target("other").previewReady)
        assertFalse(choice.bulk(true).confirmed)
        assertFalse(choice.preview(false).confirmed)
        assertFalse(choice.choose("keep_both").choose("keep_selected").confirmed)
    }
    @Test fun safeDecisionsNeedNeitherTargetNorPreview() {
        for (decision in listOf("keep_both", "keep_target")) {
            val choice = ConflictSelection().choose(decision).bulk(true)
            assertTrue(choice.canApply(false))
            assertNull(choice.body().targetMediaId)
            assertFalse(choice.body().confirmedOverwrite)
            assertTrue(choice.body().applyToAll)
        }
        assertFalse(ConflictSelection(decision = "unknown").canApply(false))
        assertTrue(runCatching { ConflictSelection(decision = "keep_selected").body() }.isFailure)
    }
    @Test fun malformedConflictTargetsCannotEnableOverwrite() {
        val target = buildJsonObject {
            put("media_id", "target"); put("filename", "İstanbul.jpg"); put("size_bytes", 2147483648L)
            put("uploaded_at", "2026-10-09T10:00:00Z")
            put("processed", buildJsonObject { put("content_type", "image/jpeg") })
        }
        fun status(value: Map<String, JsonElement>) = UploadOut(declaredSizeBytes = 1, receivedBytes = 0,
            receivedRanges = emptyList(), status = "conflict", uploadId = "saved", conflicts = listOf(value))
        assertEquals(2147483648L, conflictTargets(status(target)).single().sizeBytes)
        for ((key, value) in listOf("size_bytes" to JsonPrimitive(-1), "uploaded_at" to JsonPrimitive("bad"),
            "media_id" to JsonPrimitive(""), "filename" to JsonPrimitive("bad\nname"), "processed" to JsonPrimitive("video"))) {
            assertTrue(conflictTargets(status(target + (key to value))).isEmpty())
        }
    }
}
