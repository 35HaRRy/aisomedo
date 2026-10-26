package com.dojo.aisomedo.uploads

import com.dojo.aisomedo.api.UploadOut
import com.dojo.aisomedo.api.ApiFailure
import com.dojo.aisomedo.api.ApiTransportIssue
import kotlinx.serialization.SerializationException
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*
import java.time.OffsetDateTime

const val CHUNK_BYTES = 2 * 1024 * 1024
@Serializable data class FileIdentity(val size: Long, val chunkHashes: List<String>, val fingerprint: String)
@Serializable enum class UploadIntent { ACTIVE, PAUSED }
@Serializable enum class UploadPhase { PREPARING, WAITING, UPLOADING, PAUSED, RETRYABLE, NEEDS_FILE, QUEUED, PROCESSING, FINALIZED, FAILED, CONFLICT, EXPIRED, SKIPPED }
@Serializable enum class UploadIssue { NETWORK, TIMEOUT, DNS, TLS, RATE_LIMIT, FORBIDDEN, INVALID_INPUT, OVERSIZE, CAPACITY, PACKAGE_CHANGED, CHECKSUM, WRONG_FILE, FILE_ACCESS, STORAGE, SCHEDULING, NOTIFICATIONS, EXPIRED, CONFLICT, AUTH, UPDATE_REQUIRED, SERVER, INVALID_RESPONSE }
class UploadFailure(val issue: UploadIssue) : Exception("Upload failure: ${issue.name}")
enum class QueueOutcome { IDLE, RETRY, AUTH_REQUIRED, UPDATE_REQUIRED }

internal fun uploadIssue(error: Exception): UploadIssue = when (error) {
    is UploadFailure -> error.issue
    is SerializationException -> UploadIssue.INVALID_RESPONSE
    is ApiFailure -> when (error.status) {
        0 -> when (error.transportIssue) {
            ApiTransportIssue.TIMEOUT -> UploadIssue.TIMEOUT
            ApiTransportIssue.DNS -> UploadIssue.DNS
            ApiTransportIssue.TLS -> UploadIssue.TLS
            ApiTransportIssue.STORAGE -> UploadIssue.STORAGE
            ApiTransportIssue.INVALID_RESPONSE -> UploadIssue.INVALID_RESPONSE
            else -> UploadIssue.NETWORK
        }
        401 -> UploadIssue.AUTH
        426 -> UploadIssue.UPDATE_REQUIRED
        403 -> UploadIssue.FORBIDDEN
        404 -> UploadIssue.EXPIRED
        408, 504 -> UploadIssue.TIMEOUT
        413 -> UploadIssue.OVERSIZE
        429 -> UploadIssue.RATE_LIMIT
        409 -> when {
            error.detail?.contains("changed", true) == true -> UploadIssue.PACKAGE_CHANGED
            error.detail?.contains("package limit", true) == true -> UploadIssue.CAPACITY
            else -> UploadIssue.SERVER
        }
        400, 422 -> if (error.detail?.contains("checksum", true) == true) UploadIssue.CHECKSUM else UploadIssue.INVALID_INPUT
        else -> UploadIssue.SERVER
    }
    is java.io.IOException, is SecurityException -> UploadIssue.FILE_ACCESS
    else -> UploadIssue.SERVER
}

@Serializable data class UploadRecord(
    val id: String, val origin: String, val bindingId: String, val uri: String,
    val filename: String, val contentType: String, val clientId: Int, val size: Long? = null,
    val identity: FileIdentity? = null, val status: UploadOut? = null,
    val intent: UploadIntent = UploadIntent.ACTIVE, val phase: UploadPhase = UploadPhase.WAITING,
    val issue: UploadIssue? = null, val diagnostic: String? = null,
    val revision: Long = 0, val failures: Int = 0, val retryAtMillis: Long? = null,
    val pendingDecision: String? = null,
    val expectedPackageId: Int? = null,
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
