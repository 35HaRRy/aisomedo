package com.dojo.aisomedo.auth

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class CredentialUnavailable : Exception("Credential storage unavailable")

class SessionStore(private val directory: File, private val keyProvider: () -> SecretKey) {
    private val originFile = File(directory, "server.txt")
    private val tokenFile = File(directory, "credential.bin")
    val origin: String? get() = originFile.takeIf { it.exists() }?.readText()?.takeIf { it.isNotBlank() }

    @Synchronized fun setOrigin(value: String) {
        if (origin != value) clearToken()
        writeAtomically(originFile, value.toByteArray(Charsets.UTF_8))
    }

    @Synchronized fun readToken(origin: String): String? {
        if (origin != this.origin || !tokenFile.exists()) return null
        return try {
            val bytes = tokenFile.readBytes()
            require(bytes.size in 29..65536)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, keyProvider(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
            cipher.updateAAD(origin.toByteArray(Charsets.UTF_8))
            cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8).also { require(it.isNotBlank()) }
        } catch (_: Exception) { throw CredentialUnavailable() }
    }

    @Synchronized fun saveToken(origin: String, token: String) {
        try {
            require(origin == this.origin && token.isNotBlank() && token.length <= 16384)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, keyProvider())
            cipher.updateAAD(origin.toByteArray(Charsets.UTF_8))
            writeAtomically(tokenFile, cipher.iv + cipher.doFinal(token.toByteArray(Charsets.UTF_8)))
        } catch (_: Exception) { throw CredentialUnavailable() }
    }

    @Synchronized fun clearToken() {
        if (tokenFile.exists() && !tokenFile.delete()) throw CredentialUnavailable()
    }

    private fun writeAtomically(file: File, bytes: ByteArray) {
        directory.mkdirs()
        val temporary = File(directory, file.name + ".tmp")
        try {
            FileOutputStream(temporary).use { it.write(bytes); it.fd.sync() }
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } finally { temporary.delete() }
    }
}

fun androidKeystoreKey(alias: String = "dojo-device-token"): SecretKey {
    val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (store.getKey(alias, null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
        init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
    }.generateKey()
}
