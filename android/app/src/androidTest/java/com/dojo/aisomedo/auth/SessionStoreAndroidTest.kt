package com.dojo.aisomedo.auth

import androidx.test.platform.app.InstrumentationRegistry
import java.security.KeyStore
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class SessionStoreAndroidTest {
    @Test fun encryptedTokenUsesRealKeystoreAndFailsAfterKeyLoss() {
        val alias = "dojo-test-${UUID.randomUUID()}"
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val dir = context.noBackupFilesDir.resolve(alias).apply { mkdirs() }
        try {
            val store = SessionStore(dir) { androidKeystoreKey(alias) }
            store.setOrigin("https://example.com")
            store.saveToken("https://example.com", "SYNTHETIC")
            assertEquals("SYNTHETIC", store.readToken("https://example.com"))
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
            assertThrows(CredentialUnavailable::class.java) { store.readToken("https://example.com") }
        } finally {
            dir.deleteRecursively()
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(alias) }
        }
    }
}
