package com.dojo.aisomedo.offline

import com.dojo.aisomedo.api.*
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class SnapshotStoreTest {
    private val origin = "https://dojo.example"
    private val binding = "a".repeat(64)
    private fun content() = CachedContent(binding, ClientOut("now", "cli", 1, "device", null, "Telefon", null), SetupOut(emptyList(), true),
        activity = ActivityPageOut(emptyList(), null), activityFetchedAt = 1234)

    @Test fun roundtripDoesNotPersistDraftsOrCredentials() {
        val dir = Files.createTempDirectory("snapshot").toFile()
        try {
            val saved = SnapshotStore(dir).update(origin) { it.copy(data = content(), updateUrl = "https://dojo.example/release", compat = CompatInfo("0.1", 1, 5, "https://dojo.example/release")) }
            assertEquals(saved, SnapshotStore(dir).read(origin, binding))
            val json = dir.resolve("snapshot.json").readText()
            assertFalse(json.contains("token")); assertFalse(json.contains("draft"))
            assertFalse(json.contains("pendingDecision"))
            assertEquals("Telefon", SnapshotStore(dir).read(origin, binding)!!.data!!.client.name)
        } finally { dir.deleteRecursively() }
    }
    @Test fun mismatchedBindingKeepsOnlyOriginScopedUpdate() {
        val dir = Files.createTempDirectory("snapshot-scope").toFile()
        try {
            val store = SnapshotStore(dir)
            store.update(origin) { it.copy(data = content(), rejectedVersionCode = 5, updateUrl = "https://dojo.example/release") }
            assertNull(store.read("https://other.example", binding))
            assertNull(store.read(origin, "b".repeat(64))!!.data)
            assertEquals(5, store.read(origin, null)!!.rejectedVersionCode)
            assertEquals("https://dojo.example/release", store.read(origin, null)!!.updateUrl)
            store.clear(); assertNull(store.read(origin, binding))
        } finally { dir.deleteRecursively() }
    }
    @Test fun invalidFilesAreMisses() {
        val dir = Files.createTempDirectory("snapshot-invalid").toFile()
        try {
            val file = dir.resolve("snapshot.json")
            val saved = CachedSnapshot(origin = origin, data = content())
            for (value in listOf(saved.copy(schemaVersion = 2), saved.copy(data = content().copy(bindingId = "invalid")),
                saved.copy(data = content().copy(activityFetchedAt = -1)), saved.copy(updateUrl = "javascript:alert(1)"))) {
                file.writeText(Json.encodeToString(value))
                assertNull(SnapshotStore(dir).read(origin, binding))
            }
            file.writeText("not json"); assertNull(SnapshotStore(dir).read(origin, binding))
            file.writeBytes(ByteArray(SnapshotStore.MAX_BYTES + 1)); assertNull(SnapshotStore(dir).read(origin, binding))
        } finally { dir.deleteRecursively() }
    }
    @Test fun failedReplacementPreservesPriorSnapshot() {
        val dir = Files.createTempDirectory("snapshot-atomic").toFile()
        try {
            val store = SnapshotStore(dir)
            store.update(origin) { it.copy(data = content()) }
            val before = dir.resolve("snapshot.json").readBytes()
            assertTrue(runCatching { store.update(origin) { it.copy(data = content().copy(client = content().client.copy(name = "x".repeat(SnapshotStore.MAX_BYTES)))) } }.isFailure)
            assertArrayEquals(before, dir.resolve("snapshot.json").readBytes())
            assertEquals("Telefon", store.read(origin, binding)!!.data!!.client.name)
        } finally { dir.deleteRecursively() }
    }
    @Test fun successfulEmptyReadIsNotMissing() {
        val dir = Files.createTempDirectory("snapshot-empty").toFile()
        try {
            val store = SnapshotStore(dir)
            store.update(origin) { it.copy(data = content()) }
            assertTrue(store.read(origin, binding)!!.data!!.activity!!.events.isEmpty())
            assertEquals(1234L, store.read(origin, binding)!!.data!!.activityFetchedAt)
            store.update(origin) { it.copy(data = content().copy(activity = null, activityFetchedAt = null, editorFetchedAt = 1234)) }
            assertNull(store.read(origin, binding)!!.data!!.activityFetchedAt)
            assertEquals(1234L, store.read(origin, binding)!!.data!!.editorFetchedAt)
        } finally { dir.deleteRecursively() }
    }
}
