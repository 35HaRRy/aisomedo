package com.dojo.aisomedo.editor

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class DraftStoreTest {
    private val origin = "https://dojo.example"
    private val binding = "a".repeat(64)
    private fun draft() = StoredDraft(folderName = "active", baseContentRevision = 1,
        groups = mapOf("video:a" to DraftGroup(
            buildJsonObject { put("ranges", JsonArray(emptyList())) },
            buildJsonObject { put("ranges", buildJsonArray { add(buildJsonObject { put("start", "0"); put("end", "") }) }) })),
        inputs = mapOf("a" to listOf(RangeInput("0", ""))))

    @Test fun reopenPreservesIncompleteDraft() {
        val directory = Files.createTempDirectory("editor-drafts").toFile()
        try {
            DraftStore(directory).write(origin, binding, 1, draft())
            val reopened = DraftStore(directory).read(origin, binding, 1)!!
            assertEquals("", reopened.inputs.getValue("a")[0].end)
            assertEquals(draft(), reopened)
        } finally { directory.deleteRecursively() }
    }

    @Test fun failedReplacementPreservesPreviousDraft() {
        val directory = Files.createTempDirectory("editor-drafts").toFile()
        try {
            val store = DraftStore(directory); val previous = draft()
            store.write(origin, binding, 1, previous)
            val target = directory.walkTopDown().single { it.extension == "json" }
            val temporary = target.resolveSibling(target.nameWithoutExtension + ".tmp")
            temporary.mkdirs(); temporary.resolve("locked").writeText("fixture")
            assertNotNull(runCatching { store.write(origin, binding, 1, previous.copy(uncertain = true)) }.exceptionOrNull())
            assertEquals(previous, store.read(origin, binding, 1))
        } finally { directory.deleteRecursively() }
    }

    @Test fun otherBindingCannotRestore() {
        val directory = Files.createTempDirectory("editor-drafts").toFile()
        try {
            val store = DraftStore(directory); store.write(origin, binding, 1, draft())
            store.write(origin, "b".repeat(64), 2, draft())
            assertNull(store.read(origin, "b".repeat(64), 1))
            assertNull(store.read("https://other.example", binding, 1))
            store.clearIdentity(origin, binding)
            assertNull(store.read(origin, binding, 1))
            assertNotNull(store.read(origin, "b".repeat(64), 2))
        } finally { directory.deleteRecursively() }
    }

    @Test fun corruptOrUnsupportedDraftIsReportedAndNeverDeleted() {
        val directory = Files.createTempDirectory("editor-drafts").toFile()
        try {
            val store = DraftStore(directory); store.write(origin, binding, 1, draft())
            val file = directory.walkTopDown().single { it.extension == "json" }
            file.writeText(file.readText().replace("\"schemaVersion\":1", "\"schemaVersion\":2"))
            val before = file.readText()
            assertNotNull(runCatching { store.read(origin, binding, 1) }.exceptionOrNull())
            assertEquals(before, file.readText())
        } finally { directory.deleteRecursively() }
    }
}
