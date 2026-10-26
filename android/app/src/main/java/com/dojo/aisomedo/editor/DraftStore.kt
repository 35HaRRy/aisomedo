package com.dojo.aisomedo.editor

import com.dojo.aisomedo.api.ApiConfig
import com.dojo.aisomedo.api.readBounded
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

@Serializable data class DraftGroup(val base: JsonObject, val proposed: JsonObject)
@Serializable data class StoredDraft(
    val schemaVersion: Int = 1,
    val localRevision: Long = 0,
    val folderName: String,
    val baseContentRevision: Long,
    val groups: Map<String, DraftGroup> = emptyMap(),
    val inputs: Map<String, List<RangeInput>> = emptyMap(),
    val uncertain: Boolean = false,
    val pendingRemovals: Set<String> = emptySet(),
)
enum class DraftIssue { STORAGE, CORRUPT }
class DraftFailure(val issue: DraftIssue) : Exception("Draft recovery unavailable: $issue")

class DraftStore(private val directory: File) {
    private val json = Json { encodeDefaults = true }
    private fun scope(origin: String, bindingId: String): File {
        require(ApiConfig.normalizeOrigin(origin, true) == origin && bindingId.matches(Regex("[a-f0-9]{64}")))
        val hash = MessageDigest.getInstance("SHA-256").digest("$origin\n$bindingId".toByteArray())
            .joinToString("") { "%02x".format(it) }
        return directory.resolve(hash)
    }
    private fun file(origin: String, bindingId: String, packageId: Int): File {
        require(packageId > 0)
        return scope(origin, bindingId).resolve("$packageId.json")
    }
    @Synchronized fun read(origin: String, bindingId: String, packageId: Int): StoredDraft? {
        val target = file(origin, bindingId, packageId)
        if (!target.exists()) return null
        val bytes = try { target.inputStream().use { readBounded(it, MAX_BYTES) } }
        catch (_: Exception) { throw DraftFailure(DraftIssue.STORAGE) }
        return try { json.decodeFromString<StoredDraft>(bytes.toString(Charsets.UTF_8)).also(::validate) }
        catch (_: Exception) { throw DraftFailure(DraftIssue.CORRUPT) }
    }
    @Synchronized fun list(origin: String, bindingId: String): Map<Int, StoredDraft> =
        scope(origin, bindingId).listFiles().orEmpty().filter { it.extension == "json" }.associate { target ->
            val id = target.nameWithoutExtension.toIntOrNull()?.takeIf { it > 0 } ?: throw DraftFailure(DraftIssue.CORRUPT)
            id to requireNotNull(read(origin, bindingId, id))
        }

    @Synchronized fun write(origin: String, bindingId: String, packageId: Int, draft: StoredDraft) {
        validate(draft)
        val target = file(origin, bindingId, packageId)
        val temporary = target.resolveSibling("$packageId.tmp")
        try {
            // Do not replace a corrupt/unsupported record without an explicit user discard.
            read(origin, bindingId, packageId)
            val bytes = json.encodeToString(draft).toByteArray(Charsets.UTF_8)
            require(bytes.size <= MAX_BYTES)
            check(target.parentFile!!.isDirectory || target.parentFile!!.mkdirs())
            FileOutputStream(temporary).use { it.write(bytes); it.fd.sync() }
            Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } catch (error: DraftFailure) { throw error }
        catch (_: Exception) { throw DraftFailure(DraftIssue.STORAGE) }
        finally { temporary.delete() }
    }
    @Synchronized fun clear(origin: String, bindingId: String, packageId: Int) {
        val target = file(origin, bindingId, packageId)
        if (target.exists() && !target.delete()) throw DraftFailure(DraftIssue.STORAGE)
    }
    @Synchronized fun clearIdentity(origin: String, bindingId: String) {
        for (target in scope(origin, bindingId).listFiles().orEmpty().filter { it.extension == "json" }) {
            if (!target.delete()) throw DraftFailure(DraftIssue.STORAGE)
        }
    }
    private fun validate(draft: StoredDraft) {
        require(draft.schemaVersion == 1 && draft.localRevision >= 0 && draft.folderName.isNotBlank() && draft.baseContentRevision > 0)
        require(draft.pendingRemovals.all { it.isNotBlank() && it.length <= 128 })
        for ((key, group) in draft.groups) {
            val field = when {
                key.startsWith("video:") && key.length > 6 -> "ranges"
                key.startsWith("photo:") && key.length > 6 -> "seconds"
                key == "order" -> "ids"
                key == "caption" -> "text"
                key == "branding" -> "settings"
                else -> error("Unsupported draft group")
            }
            require(group.base.keys == setOf(field) && group.proposed.keys == setOf(field))
            if (field == "ranges") for (value in listOf(group.base, group.proposed)) {
                val ranges = value[field] as? JsonArray ?: error("Invalid draft ranges")
                for (range in ranges) {
                    val row = range as? JsonObject ?: error("Invalid draft range")
                    require(row.keys == setOf("start", "end") && row.values.all { it is JsonPrimitive && it != JsonNull })
                }
            }
        }
    }
    private companion object {
        // ponytail: 4 MiB editor metadata; stream or raise only for measured larger drafts.
        const val MAX_BYTES = 4 * 1024 * 1024
    }
}
