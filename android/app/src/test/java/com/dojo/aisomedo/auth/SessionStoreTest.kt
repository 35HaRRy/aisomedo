package com.dojo.aisomedo.auth

import com.dojo.aisomedo.api.ApiConfig
import java.nio.file.Files
import javax.crypto.KeyGenerator
import org.junit.Assert.*
import org.junit.Test

class SessionStoreTest {
    @Test fun pairingBindingRotatesWithoutLeakingCredentials() {
        val dir = Files.createTempDirectory("dojo-binding").toFile()
        try {
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            val store = SessionStore(dir) { key }
            store.setOrigin("https://example.com")
            store.saveToken("https://example.com", "FIRST-SECRET")
            val first = store.readSession("https://example.com")!!
            assertFalse(first.toString().contains("FIRST-SECRET"))
            store.saveToken("https://example.com", "SECOND-SECRET")
            assertNotEquals(first.bindingId, store.readSession("https://example.com")!!.bindingId)
            assertFalse(store.clearTokenIfBinding("https://example.com", first.bindingId))
            assertEquals("SECOND-SECRET", store.readToken("https://example.com"))
            assertTrue(store.clearTokenIfBinding("https://example.com", store.readSession("https://example.com")!!.bindingId))
            assertNull(store.readSession("https://example.com"))
        } finally { dir.deleteRecursively() }
    }
    @Test fun rejectsSecretBearingAndNonOriginUrls() {
        listOf("https://u:p@example.com", "https://example.com/api", "https://example.com?q=1", "https://example.com#x", "http://example.com", "https://example.com:99999").forEach {
            assertThrows(IllegalArgumentException::class.java) { ApiConfig.normalizeOrigin(it, false) }
        }
        assertEquals("https://example.com", ApiConfig.normalizeOrigin("https://EXAMPLE.com:443/", false))
        assertEquals("http://10.0.2.2:8000", ApiConfig.normalizeOrigin("http://10.0.2.2:8000", true))
    }

    @Test fun encryptedRoundtripOriginBindingAndCorruption() {
        val dir = Files.createTempDirectory("dojo-store").toFile()
        try {
            val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            val store = SessionStore(dir) { key }
            store.setOrigin("https://example.com")
            store.saveToken("https://example.com", "SECRET-DEVICE-TOKEN")
            assertEquals("SECRET-DEVICE-TOKEN", SessionStore(dir) { key }.readToken("https://example.com"))
            assertNull(store.readToken("https://other.example"))
            dir.listFiles()!!.forEach { assertFalse(it.readBytes().toString(Charsets.UTF_8).contains("SECRET-DEVICE-TOKEN")) }
            val other = KeyGenerator.getInstance("AES").generateKey()
            assertThrows(CredentialUnavailable::class.java) { SessionStore(dir) { other }.readToken("https://example.com") }
            store.setOrigin("https://other.example")
            assertNull(store.readToken("https://other.example"))
            store.saveToken("https://other.example", "NEW")
            dir.resolve("credential.bin").writeBytes(byteArrayOf(1))
            assertThrows(CredentialUnavailable::class.java) { store.readToken("https://other.example") }
        } finally { dir.deleteRecursively() }
    }
}
