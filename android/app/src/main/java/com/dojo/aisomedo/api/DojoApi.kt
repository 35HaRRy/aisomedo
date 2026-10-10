package com.dojo.aisomedo.api

import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.io.InputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class ApiFailure(val status: Int, val updateUrl: String? = null, val detail: String? = null) : Exception("API failure: $status")

class DojoApi(private val origin: String, private val token: String?, private val versionCode: Int, http: OkHttpClient) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = true }
    private val client = http.newBuilder().followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(10, TimeUnit.SECONDS).callTimeout(30, TimeUnit.SECONDS).build()

    private suspend fun bytes(method: String, path: String, body: RequestBody? = null, authenticated: Boolean = true,
        destination: File? = null, limit: Long = 10L * 1024 * 1024): ByteArray {
        require(path.startsWith("/api/") && !path.contains('\\'))
        val base = origin.toHttpUrl()
        val url = base.resolve(path) ?: throw IllegalArgumentException("path")
        require(url.host == base.host && url.port == base.port && url.scheme == base.scheme && url.encodedPath.startsWith("/api/"))
        val builder = Request.Builder().url(url).header("X-Android-Version-Code", versionCode.toString())
        if (authenticated && token != null) builder.header("Authorization", "Bearer $token")
        builder.method(method, body ?: if (method == "POST" || method == "PUT" || method == "PATCH") ByteArray(0).toRequestBody() else null)
        val call = client.newCall(builder.build())
        return suspendCancellableCoroutine { continuation ->
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    destination?.delete()
                    if (continuation.isActive) continuation.resumeWithException(ApiFailure(0))
                }
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        if (!continuation.isActive) { destination?.delete(); return }
                        try {
                            if (!response.isSuccessful) {
                                destination?.delete()
                                val error = runCatching {
                                    val text = response.body?.byteStream()?.use { readBounded(it, 65536).toString(Charsets.UTF_8) }.orEmpty()
                                    json.parseToJsonElement(text).jsonObject
                                }.getOrNull()
                                val update = if (response.code == 426) (error?.get("update_url") as? JsonPrimitive)?.contentOrNull else null
                                val detail = (error?.get("detail") as? JsonPrimitive)?.contentOrNull?.take(1024)
                                continuation.resumeWithException(ApiFailure(response.code, update, detail))
                            } else {
                                val source = response.body?.byteStream()
                                val data = if (destination == null) source?.use { readBounded(it, limit.toInt()) } ?: ByteArray(0)
                                else {
                                    require(source != null)
                                    source.use { input -> destination.outputStream().use { output ->
                                        val buffer = ByteArray(8192)
                                        var total = 0L
                                        while (true) {
                                            if (!continuation.isActive) throw IOException("Preview cancelled")
                                            val count = input.read(buffer)
                                            if (count < 0) break
                                            total += count
                                            if (total > limit) throw ApiFailure(413)
                                            output.write(buffer, 0, count)
                                        }
                                    } }
                                    ByteArray(0)
                                }
                                if (continuation.isActive) continuation.resume(data) else destination?.delete()
                            }
                        } catch (e: Exception) {
                            destination?.delete()
                            if (continuation.isActive) continuation.resumeWithException(if (e is ApiFailure) e else ApiFailure(0))
                        }
                    }
                }
            })
        }
    }

    suspend fun request(method: String, path: String, body: JsonElement? = null): JsonElement {
        val public = path == "/api/compat" || path == "/api/pairing/validate"
        val data = bytes(method, path, body?.toString()?.toRequestBody("application/json".toMediaType()), !public)
        return try { if (data.isEmpty()) JsonNull else json.parseToJsonElement(data.toString(Charsets.UTF_8)) }
        catch (_: SerializationException) { throw SerializationException("Invalid server response") }
    }
    private inline fun <reified T> decode(value: JsonElement): T = try { json.decodeFromJsonElement<T>(value) }
        catch (_: SerializationException) { throw SerializationException("Invalid server response") }

    suspend fun compat(): CompatInfo = decode(request("GET", "/api/compat"))
    suspend fun pair(code: String, name: String): PairingOut = decode(request("POST", "/api/pairing/validate", json.encodeToJsonElement(ValidateIn(code, "device", name))))
    suspend fun me(): ClientOut = decode(request("GET", "/api/pairing/me"))
    suspend fun dashboard(): DashboardOut = decode(request("GET", "/api/dashboard"))
    suspend fun setup(): SetupOut = decode(request("GET", "/api/setup"))
    suspend fun consent(): ConsentOut = decode(request("GET", "/api/setup/consent"))
    suspend fun acceptConsent(version: Int): AcceptanceOut = decode(request("POST", "/api/setup/consent/accept", buildJsonObject { put("version", version) }))
    suspend fun plan(): PlanOut = decode(request("GET", "/api/settings/plan"))
    suspend fun savePlan(body: PlanIn): PlanOut = decode(request("PUT", "/api/settings/plan", json.encodeToJsonElement(body)))
    suspend fun branding(): BrandingDefaultsOut = decode(request("GET", "/api/settings/branding"))
    suspend fun patchBranding(changes: JsonObject): BrandingDefaultsOut = decode(request("PATCH", "/api/settings/branding", changes))
    suspend fun skipCards(): SetupOut = decode(request("POST", "/api/setup/cards/skip"))
    suspend fun instagram(): StatusOut = decode(request("GET", "/api/meta/status"))
    suspend fun connectInstagramToken(token: String): StatusOut = decode(request("POST", "/api/meta/instagram/token", buildJsonObject { put("access_token", token) }))
    suspend fun startOAuth(): StartOut = decode(request("POST", "/api/meta/oauth/start", buildJsonObject {}))
    suspend fun oauthAttempt(id: String): AttemptOut = decode(request("GET", "/api/meta/oauth/attempts/${segment(id)}"))
    suspend fun selectAccount(attemptId: String, igUserId: String): StatusOut = decode(request("POST", "/api/meta/oauth/attempts/${segment(attemptId)}/select", buildJsonObject { put("ig_user_id", igUserId) }))
    suspend fun uploadBranding(bytes: ByteArray): BrandingAssetOut {
        require(bytes.size <= 10 * 1024 * 1024)
        val result = this.bytes("POST", "/api/settings/branding/assets", bytes.toRequestBody("application/octet-stream".toMediaType()))
        return try { json.decodeFromString<BrandingAssetOut>(result.toString(Charsets.UTF_8)) }
        catch (_: SerializationException) { throw SerializationException("Invalid server response") }
    }
    suspend fun preview(path: String): ByteArray = bytes("GET", path)
    suspend fun uploadLimits(): UploadLimitsOut = decode(request("GET", "/api/media/upload-limits"))
    suspend fun startUpload(body: UploadInitIn): UploadOut = decode(request("POST", "/api/media/uploads", json.encodeToJsonElement(body)))
    suspend fun uploadStatus(id: String): UploadOut = decode(request("GET", "/api/media/uploads/${segment(id)}"))
    suspend fun completeUpload(id: String): UploadOut = decode(request("POST", "/api/media/uploads/${segment(id)}/complete"))
    suspend fun resolveUpload(id: String, body: ResolveConflictIn): UploadOut = decode(request("POST", "/api/media/uploads/${segment(id)}/resolve", json.encodeToJsonElement(body)))
    suspend fun conflictPreview(id: String, targetId: String, file: File, limit: Long) {
        require(limit > 0)
        bytes("GET", "/api/media/uploads/${segment(id)}/conflicts/${segment(targetId)}/preview", destination = file, limit = limit)
    }
    suspend fun uploadWasSkipped(id: String): Boolean {
        // Reuse authoritative audit evidence: UploadOut cannot distinguish skip from expiry.
        // ponytail: paginate existing audit; add an upload-scoped outcome field if history scans become slow.
        var cursor: Long? = null
        while (true) {
            val page = request("GET", "/api/activity?limit=100" + (cursor?.let { "&before_id=$it" } ?: "")) as? JsonObject
                ?: throw SerializationException("Invalid activity response")
            val events = page["events"] as? JsonArray ?: throw SerializationException("Invalid activity response")
            for (value in events) {
                val event = value as? JsonObject ?: throw SerializationException("Invalid activity event")
                val action = (event["action"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                    ?: throw SerializationException("Invalid activity action")
                if (action !in setOf("conflict.resolved", "upload.expired", "upload.aborted")) continue
                val details = event["details"] as? JsonObject ?: throw SerializationException("Invalid conflict event")
                val uploadId = (details["upload_id"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                    ?: throw SerializationException("Invalid conflict upload")
                if (uploadId != id) continue
                if (action != "conflict.resolved") return false
                val decision = (details["decision"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                if (decision !in setOf("keep_both", "keep_selected", "keep_target")) throw SerializationException("Invalid conflict decision")
                return decision == "keep_target"
            }
            val next = page["next_cursor"] ?: throw SerializationException("Missing activity cursor")
            // State and audit writes are separate. Missing evidence is still unknown, not expiry.
            if (next == JsonNull) throw ApiFailure(0)
            val number = (next as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
                ?: throw SerializationException("Invalid activity cursor")
            if (number <= 0 || (cursor != null && number >= cursor)) throw SerializationException("Invalid activity cursor")
            cursor = number
        }
    }
    suspend fun uploadRange(id: String, offset: Long, checksum: String, bytes: ByteArray): UploadOut {
        require(offset >= 0 && checksum.matches(Regex("[a-f0-9]{64}")) && bytes.isNotEmpty() && bytes.size <= 2 * 1024 * 1024)
        val result = this.bytes("PUT", "/api/media/uploads/${segment(id)}/ranges?offset=$offset&checksum_sha256=$checksum",
            bytes.toRequestBody("application/octet-stream".toMediaType()))
        return try { json.decodeFromString<UploadOut>(result.toString(Charsets.UTF_8)) }
        catch (_: SerializationException) { throw SerializationException("Invalid server response") }
    }
    private fun segment(value: String) = URLEncoder.encode(value, "UTF-8").replace("+", "%20")
}

fun readBounded(input: InputStream, limit: Int): ByteArray {
    val output = ByteArrayOutputStream()
    val buffer = ByteArray(8192)
    while (true) {
        val count = input.read(buffer, 0, minOf(buffer.size, limit - output.size() + 1))
        if (count < 0) return output.toByteArray()
        if (output.size() + count > limit) throw ApiFailure(413)
        output.write(buffer, 0, count)
    }
}
