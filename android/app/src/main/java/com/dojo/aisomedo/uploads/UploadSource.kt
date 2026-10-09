package com.dojo.aisomedo.uploads

import android.content.ContentResolver
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.*
import java.io.InputStream
import java.security.MessageDigest

data class SelectedDocument(val uri: String, val filename: String, val contentType: String, val size: Long?)

class UploadSource(private val resolver: ContentResolver) {
    fun retain(uri: Uri): SelectedDocument = try {
        require(uri.scheme == "content")
        resolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        require(resolver.persistedUriPermissions.any { it.uri == uri && it.isReadPermission })
        var name = uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "media"
        var size: Long? = null
        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameColumn = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeColumn = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameColumn >= 0 && !cursor.isNull(nameColumn)) name = cursor.getString(nameColumn)
                if (sizeColumn >= 0 && !cursor.isNull(sizeColumn)) size = cursor.getLong(sizeColumn).takeIf { it >= 0 }
            }
        }
        SelectedDocument(uri.toString(), name, resolver.getType(uri) ?: "application/octet-stream", size)
    } catch (_: Exception) { throw UploadFailure(UploadIssue.FILE_ACCESS) }
    fun open(uri: String): InputStream = try { resolver.openInputStream(Uri.parse(uri)) ?: throw UploadFailure(UploadIssue.FILE_ACCESS) }
        catch (_: Exception) { throw UploadFailure(UploadIssue.FILE_ACCESS) }
    fun release(uri: String) { resolver.releasePersistableUriPermission(Uri.parse(uri), Intent.FLAG_GRANT_READ_URI_PERMISSION) }
}

internal fun sha256(bytes: ByteArray, count: Int = bytes.size): String = MessageDigest.getInstance("SHA-256").apply { update(bytes, 0, count) }
    .digest().joinToString("") { "%02x".format(it) }

@OptIn(InternalCoroutinesApi::class)
internal suspend fun scanChunks(open: () -> InputStream, limit: Long = Long.MAX_VALUE, visit: suspend (Long, ByteArray, Int) -> Unit): Long = withContext(Dispatchers.IO) {
    val context = currentCoroutineContext()
    open().use { input ->
        val closer = context[Job]?.invokeOnCompletion(onCancelling = true, invokeImmediately = true) { cause ->
            if (cause != null) runCatching { input.close() }
        }
        try {
            val buffer = ByteArray(CHUNK_BYTES)
            var offset = 0L
            while (true) {
                context.ensureActive()
                val allowed = if (limit - offset < CHUNK_BYTES) (limit - offset + 1).toInt() else CHUNK_BYTES
                var count = 0
                while (count < allowed) {
                    context.ensureActive()
                    val read = input.read(buffer, count, allowed - count)
                    if (read < 0) break
                    if (read == 0) {
                        val byte = input.read()
                        if (byte < 0) break
                        buffer[count++] = byte.toByte()
                    } else count += read
                }
                if (count == 0) return@withContext offset
                if (count.toLong() > limit - offset) throw UploadFailure(UploadIssue.OVERSIZE)
                visit(offset, buffer, count)
                offset += count
            }
            @Suppress("UNREACHABLE_CODE") offset
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            context.ensureActive()
            if (e is UploadFailure) throw e
            throw UploadFailure(UploadIssue.FILE_ACCESS)
        } finally { closer?.dispose() }
    }
}

suspend fun prepareFile(open: () -> InputStream, declaredSize: Long?, maxBytes: Long, onProgress: (Long) -> Unit): FileIdentity {
    if (maxBytes <= 0) throw UploadFailure(UploadIssue.INVALID_RESPONSE)
    if (declaredSize != null && (declaredSize <= 0 || declaredSize > maxBytes)) throw UploadFailure(UploadIssue.OVERSIZE)
    val hashes = mutableListOf<String>()
    val size = scanChunks(open, maxBytes) { offset, bytes, count -> hashes.add(sha256(bytes, count)); onProgress(offset + count) }
    if (size == 0L) throw UploadFailure(UploadIssue.OVERSIZE)
    if (declaredSize != null && size != declaredSize) throw UploadFailure(UploadIssue.WRONG_FILE)
    return FileIdentity(size, hashes, sha256(("$size:$CHUNK_BYTES:" + hashes.joinToString("")).toByteArray()))
}
suspend fun verifyFile(open: () -> InputStream, expected: FileIdentity, onProgress: (Long) -> Unit) {
    val actual = prepareFile(open, expected.size, expected.size, onProgress)
    if (actual != expected) throw UploadFailure(UploadIssue.WRONG_FILE)
}
