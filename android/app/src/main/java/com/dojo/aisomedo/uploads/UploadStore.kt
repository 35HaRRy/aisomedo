package com.dojo.aisomedo.uploads

import com.dojo.aisomedo.api.ApiConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.io.FileOutputStream
import java.net.URI
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

@Serializable private data class SavedUpload(val version: Int = 1, val row: UploadRecord)

class UploadStore(private val directory: File) {
    private val json = Json { ignoreUnknownKeys = true }
    private val mutable = MutableStateFlow(load())
    val rows = mutable.asStateFlow()
    // ponytail: same-process lock; use transactional storage if multiple processes are introduced.
    @Synchronized fun put(record: UploadRecord) {
        validate(record)
        if (mutable.value.any { it.id == record.id }) throw UploadFailure(UploadIssue.STORAGE)
        write(record)
        mutable.value = mutable.value + record
    }
    @Synchronized fun mutate(id: String, expectedRevision: Long? = null, change: (UploadRecord) -> UploadRecord): UploadRecord? {
        val before = mutable.value.find { it.id == id } ?: return null
        if (expectedRevision != null && before.revision != expectedRevision) return null
        val after = change(before).copy(revision = Math.addExact(before.revision, 1))
        require(after.id == before.id && after.origin == before.origin && after.bindingId == before.bindingId && after.clientId == before.clientId)
        validate(after)
        write(after)
        mutable.value = mutable.value.map { if (it.id == id) after else it }
        return after
    }
    @Synchronized fun remove(id: String) {
        val row = mutable.value.find { it.id == id } ?: return
        val file = File(directory, "${row.id}.json")
        if (file.exists() && !file.delete()) throw UploadFailure(UploadIssue.STORAGE)
        mutable.value = mutable.value.filterNot { it.id == id }
    }
    private fun load(): List<UploadRecord> = directory.listFiles()?.filter { it.extension == "json" }?.mapNotNull { file ->
        runCatching {
            require(file.length() in 1..MAX_RECORD_BYTES.toLong())
            val saved = json.decodeFromString<SavedUpload>(file.readText())
            require(saved.version == 1 && file.nameWithoutExtension == saved.row.id)
            validate(saved.row)
            saved.row
        }.getOrNull()
    }.orEmpty()
    private fun validate(row: UploadRecord) {
        try {
            require(UUID.fromString(row.id).toString() == row.id && row.clientId > 0)
            require(ApiConfig.normalizeOrigin(row.origin, true) == row.origin)
            require(row.bindingId.matches(Regex("[a-f0-9]{64}")) && URI(row.uri).scheme == "content")
            require(row.filename.isNotBlank() && row.filename.length <= 1024 && row.contentType.length in 1..256)
            require(row.size == null || row.size > 0)
            require(row.revision >= 0 && row.failures in 0..5 && (row.retryAtMillis == null || row.retryAtMillis >= 0))
            row.identity?.let {
                require(row.size == it.size && it.size > 0 && it.chunkHashes.size.toLong() == (it.size - 1) / CHUNK_BYTES + 1)
                require((it.chunkHashes + it.fingerprint).all { hash -> hash.matches(Regex("[a-f0-9]{64}")) })
                require(it.fingerprint == sha256(("${it.size}:$CHUNK_BYTES:" + it.chunkHashes.joinToString("")).toByteArray()))
            }
            row.status?.let { require(row.identity != null); validateStatus(it, row.size!! ) }
            require(row.diagnostic == null || row.diagnostic.length <= 1024)
            require(row.pendingDecision == null || row.pendingDecision in conflictDecisions)
        } catch (_: Exception) { throw UploadFailure(UploadIssue.STORAGE) }
    }
    private fun write(row: UploadRecord) {
        val temporary = File(directory, "${row.id}.tmp")
        try {
            val bytes = json.encodeToString(SavedUpload.serializer(), SavedUpload(row = row)).toByteArray()
            // ponytail: 1 MiB metadata per file; raise bound or stream metadata for much larger configured files.
            require(bytes.size <= MAX_RECORD_BYTES && (directory.isDirectory || directory.mkdirs()))
            FileOutputStream(temporary).use { it.write(bytes); it.fd.sync() }
            Files.move(temporary.toPath(), File(directory, "${row.id}.json").toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        } catch (_: Exception) { throw UploadFailure(UploadIssue.STORAGE) }
        finally { temporary.delete() }
    }
    private companion object { const val MAX_RECORD_BYTES = 1024 * 1024 }
}
