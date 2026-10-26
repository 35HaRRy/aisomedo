package com.dojo.aisomedo.uploads

import com.dojo.aisomedo.auth.SessionStore
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files
import java.util.UUID
import javax.crypto.KeyGenerator

class RetainedDocumentTest {
    private val origin = "https://dojo.example"
    private val document = SelectedDocument("content://test/new", "new.jpg", "image/jpeg", 1)
    @Test fun lateDocumentReadCannotEnqueueAfterDisconnect() = runBlocking {
        val directory = Files.createTempDirectory("late-document").toFile()
        try {
            val store = UploadStore(directory)
            var connected = true; var released = false
            val committed = retainAndCommit({ connected = false; document }, { connected }, { released = true }) {
                store.put(UploadRecord(UUID.randomUUID().toString(), origin, "a".repeat(64), it.uri, it.filename, it.contentType, 1, it.size)); true
            }
            assertFalse(committed); assertTrue(store.rows.value.isEmpty()); assertTrue(released)
        } finally { directory.deleteRecursively() }
    }
    @Test fun lateVerificationCannotReplaceAfterPairingChange() = runBlocking {
        val directory = Files.createTempDirectory("late-verification").toFile()
        try {
            val key = KeyGenerator.getInstance("AES").generateKey()
            val session = SessionStore(directory.resolve("session")) { key }
            session.setOrigin(origin); session.saveToken(origin, "OLD-SYNTHETIC")
            val binding = session.readSession(origin)!!.bindingId
            val store = UploadStore(directory.resolve("uploads"))
            val original = UploadRecord(UUID.randomUUID().toString(), origin, binding, "content://test/original", "old.jpg", "image/jpeg", 1, 1)
            store.put(original)
            var released = false
            val committed = retainAndCommit({ document }, { session.readSession(origin)?.bindingId == binding }, { released = true },
                verify = { session.saveToken(origin, "NEW-SYNTHETIC") }) {
                store.mutate(original.id, original.revision) { row -> row.copy(uri = it.uri) } != null
            }
            assertFalse(committed); assertEquals(original, store.rows.value.single()); assertTrue(released)
            assertEquals("NEW-SYNTHETIC", session.readToken(origin))
        } finally { directory.deleteRecursively() }
    }
    @Test fun currentFileIsCommittedAndGrantRetained() = runBlocking {
        val directory = Files.createTempDirectory("current-document").toFile()
        try {
            val store = UploadStore(directory); var released = false
            assertTrue(retainAndCommit({ document }, { true }, { released = true }) {
                store.put(UploadRecord(UUID.randomUUID().toString(), origin, "a".repeat(64), it.uri, it.filename, it.contentType, 1, it.size)); true
            })
            assertEquals(document.uri, store.rows.value.single().uri); assertFalse(released)
        } finally { directory.deleteRecursively() }
    }
    @Test fun failedRowCommitReleasesNewPermission() = runBlocking {
        var released = false
        assertFalse(retainAndCommit({ document }, { true }, { released = true }) { false })
        assertTrue(released)
    }
}
