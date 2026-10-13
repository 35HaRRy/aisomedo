package com.dojo.aisomedo.offline

import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.safeExternalUrl
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption

@Serializable data class CachedSnapshot(
    val schemaVersion: Int = 1, val origin: String, val compat: CompatInfo? = null,
    val updateUrl: String? = null, val rejectedVersionCode: Int? = null, val data: CachedContent? = null,
)
@Serializable data class CachedContent(
    val bindingId: String, val client: ClientOut, val setup: SetupOut,
    val dashboard: DashboardOut? = null, val editor: ActiveEditorOut? = null, val activity: ActivityPageOut? = null,
    val dashboardFetchedAt: Long? = null, val editorFetchedAt: Long? = null, val activityFetchedAt: Long? = null,
)

class SnapshotStore(private val directory: File) {
    private val json = Json { ignoreUnknownKeys = true }
    private val file = directory.resolve("snapshot.json")
    @Synchronized fun read(origin: String, bindingId: String?): CachedSnapshot? {
        val value = load()?.takeIf { it.origin == origin } ?: return null
        return value.copy(data = value.data?.takeIf { it.bindingId == bindingId })
    }
    @Synchronized fun update(origin: String, change: (CachedSnapshot) -> CachedSnapshot): CachedSnapshot {
        val value = change(load()?.takeIf { it.origin == origin } ?: CachedSnapshot(origin = origin))
        require(value.origin == origin)
        validate(value)
        val bytes = json.encodeToString(value).toByteArray(Charsets.UTF_8)
        require(bytes.size <= MAX_BYTES)
        check(directory.isDirectory || directory.mkdirs())
        val temporary = directory.resolve("snapshot.tmp")
        try {
            FileOutputStream(temporary).use { it.write(bytes); it.fd.sync() }
            Files.move(temporary.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } finally { temporary.delete() }
        return value
    }
    @Synchronized fun clear() { if (file.exists()) check(file.delete()) }
    private fun load(): CachedSnapshot? = runCatching {
        require(file.length() in 1..MAX_BYTES.toLong())
        json.decodeFromString<CachedSnapshot>(file.inputStream().use { readBounded(it, MAX_BYTES) }.toString(Charsets.UTF_8)).also(::validate)
    }.getOrNull()
    private fun validate(value: CachedSnapshot) {
        require(value.schemaVersion == 1 && ApiConfig.normalizeOrigin(value.origin, true) == value.origin)
        require(value.updateUrl == null || safeExternalUrl(value.updateUrl) == value.updateUrl)
        require(value.rejectedVersionCode == null || value.rejectedVersionCode > 0)
        value.compat?.let { require(it.androidMinVersionCode > 0 && it.androidCurrentVersionCode >= it.androidMinVersionCode) }
        value.data?.let {
            require(it.bindingId.matches(Regex("[a-f0-9]{64}")))
            require(it.client.id > 0 && it.client.kind == "device" && it.client.revokedAt == null)
            require(listOfNotNull(it.dashboardFetchedAt, it.editorFetchedAt, it.activityFetchedAt).all { time -> time >= 0 })
            require(it.dashboard == null || it.dashboardFetchedAt != null)
            require(it.editor == null || it.editorFetchedAt != null)
            require(it.activity == null || (it.activityFetchedAt != null && it.activity.events.size <= 50))
        }
    }
    companion object {
        // ponytail: 4 MiB metadata snapshot; expand bound or stream if real package metadata exceeds it.
        const val MAX_BYTES = 4 * 1024 * 1024
    }
}
