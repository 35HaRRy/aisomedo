package com.dojo.aisomedo.uploads

import com.dojo.aisomedo.api.UploadOut
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*
import java.time.OffsetDateTime

const val CHUNK_BYTES = 2 * 1024 * 1024
@Serializable data class FileIdentity(val size: Long, val chunkHashes: List<String>, val fingerprint: String)
@Serializable enum class UploadIntent { ACTIVE, PAUSED }
@Serializable enum class UploadPhase { PREPARING, WAITING, UPLOADING, PAUSED, RETRYABLE, NEEDS_FILE, QUEUED, PROCESSING, FINALIZED, FAILED, CONFLICT, EXPIRED, SKIPPED }
@Serializable enum class UploadIssue { NETWORK, OVERSIZE, CAPACITY, PACKAGE_CHANGED, CHECKSUM, WRONG_FILE, FILE_ACCESS, STORAGE, SCHEDULING, NOTIFICATIONS, EXPIRED, CONFLICT, AUTH, UPDATE_REQUIRED, SERVER, INVALID_RESPONSE }
class UploadFailure(val issue: UploadIssue) : Exception("Upload failure: ${issue.name}")
enum class QueueOutcome { IDLE, RETRY, AUTH_REQUIRED, UPDATE_REQUIRED }

@Serializable data class UploadRecord(
    val id: String, val origin: String, val bindingId: String, val uri: String,
    val filename: String, val contentType: String, val clientId: Int, val size: Long? = null,
    val identity: FileIdentity? = null, val status: UploadOut? = null,
    val intent: UploadIntent = UploadIntent.ACTIVE, val phase: UploadPhase = UploadPhase.WAITING,
    val issue: UploadIssue? = null, val diagnostic: String? = null,
    val revision: Long = 0, val failures: Int = 0, val retryAtMillis: Long? = null,
    val pendingDecision: String? = null,
)

val conflictDecisions = setOf("keep_both", "keep_selected", "keep_target")
data class ConflictTarget(val mediaId: String, val filename: String, val sizeBytes: Long, val uploadedAt: String, val contentType: String)

fun conflictTargets(status: UploadOut?): List<ConflictTarget> = status?.conflicts.orEmpty().mapNotNull { value ->
    runCatching {
        fun text(key: String) = (value[key] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: error(key)
        val id = text("media_id").also { require(it.isNotBlank() && it.length <= 128) }
        val name = text("filename").also { require(it.isNotBlank() && it.length <= 1024 && it.none(Char::isISOControl)) }
        val size = (value["size_bytes"] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull ?: error("size")
        require(size >= 0)
        val date = text("uploaded_at").also { OffsetDateTime.parse(it) }
        val type = (value["processed"] as? JsonObject)?.get("content_type")?.jsonPrimitive?.takeIf { it.isString }?.content
        require(type in setOf("image/jpeg", "video/mp4"))
        ConflictTarget(id, name, size, date, type!!)
    }.getOrNull()
}.distinctBy { it.mediaId }

fun validateStatus(status: UploadOut, size: Long, id: String? = null) {
    fun check(value: Boolean) { if (!value) throw UploadFailure(UploadIssue.INVALID_RESPONSE) }
    check(status.uploadId.isNotBlank() && status.uploadId.length <= 128 && (id == null || status.uploadId == id))
    check(size > 0 && status.declaredSizeBytes == size && status.receivedBytes in 0..size)
    check(status.status in setOf("receiving", "conflict", "queued", "processing", "finalized", "failed", "aborted"))
    var end = 0L
    var received = 0L
    status.receivedRanges.forEach { range ->
        check(range.size == 2)
        check(range[0] >= end && range[1] > range[0] && range[1] <= size)
        received += range[1] - range[0]
        end = range[1]
    }
    check(received == status.receivedBytes)
}
