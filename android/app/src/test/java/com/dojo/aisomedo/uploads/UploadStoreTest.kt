package com.dojo.aisomedo.uploads

import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import java.util.UUID

class UploadStoreTest {
    @Test fun inconsistentFingerprintIsRejected() {
        val dir = Files.createTempDirectory("dojo-upload-identity").toFile()
        try {
            val row = UploadRecord(UUID.randomUUID().toString(), "https://example.com", "a".repeat(64), "content://documents/1", "photo.jpg", "image/jpeg", 1, 2,
                identity = FileIdentity(2, listOf("b".repeat(64)), "c".repeat(64)))
            assertEquals(UploadIssue.STORAGE, (runCatching { UploadStore(dir).put(row) }.exceptionOrNull() as? UploadFailure)?.issue)
        } finally { dir.deleteRecursively() }
    }
    @Test fun recordsReloadAndRejectStaleMutation() {
        val dir = Files.createTempDirectory("dojo-upload-store").toFile()
        try {
            val store = UploadStore(dir)
            val row = UploadRecord(UUID.randomUUID().toString(), "https://example.com", "a".repeat(64), "content://documents/1", "photo.jpg", "image/jpeg", 1, 2)
            store.put(row)
            val paused = store.mutate(row.id, 0) { it.copy(intent = UploadIntent.PAUSED, phase = UploadPhase.PAUSED) }!!
            assertEquals(1L, paused.revision)
            assertNull(store.mutate(row.id, 0) { it.copy(intent = UploadIntent.ACTIVE) })
            assertEquals(paused, UploadStore(dir).rows.value.single())
        } finally { dir.deleteRecursively() }
    }
    @Test fun corruptionAndFailedWritesCannotSchedule() {
        val dir = Files.createTempDirectory("dojo-upload-bad").toFile()
        try {
            dir.resolve("${UUID.randomUUID()}.json").writeText("{invalid}")
            dir.resolve("${UUID.randomUUID()}.json").writeText("""{"version":2,"row":{}}""")
            dir.resolve("${UUID.randomUUID()}.json").writeText(" ".repeat(1024 * 1024 + 1))
            assertTrue(UploadStore(dir).rows.value.isEmpty())
            val blocked = dir.resolve("file").apply { writeText("not a directory") }
            val store = UploadStore(blocked)
            val row = UploadRecord(UUID.randomUUID().toString(), "https://example.com", "a".repeat(64), "content://documents/1", "photo.jpg", "image/jpeg", 1, 2)
            assertEquals(UploadIssue.STORAGE, (runCatching { store.put(row) }.exceptionOrNull() as UploadFailure).issue)
            assertTrue(store.rows.value.isEmpty())
        } finally { dir.deleteRecursively() }
    }
}
