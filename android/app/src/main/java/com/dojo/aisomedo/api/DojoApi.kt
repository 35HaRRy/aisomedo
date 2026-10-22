package com.dojo.aisomedo.api

import android.util.Log
import com.dojo.aisomedo.BuildConfig
import com.dojo.aisomedo.live.LiveEvent
import com.dojo.aisomedo.live.readLiveEvents
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.delay
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
import java.util.concurrent.atomic.AtomicLong
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

enum class ApiTransportIssue { TIMEOUT, DNS, TLS, CONNECTION, STORAGE, INVALID_RESPONSE }
class ApiFailure(val status: Int, val updateUrl: String? = null, val detail: String? = null,
    val transportIssue: ApiTransportIssue? = null, val editConflict: EditConflictOut? = null) : Exception("API failure: $status")

class SnapshotSuperseded : Exception("Snapshot superseded")
/** Shared only by one paired ViewModel; observations fence late or pre-change HTTP bodies. */
class SnapshotVersions {
    private var epoch = 0L
    private val values = mutableMapOf<String, Long>()
    @Synchronized fun epoch() = epoch
    @Synchronized fun reset() { epoch++; values.clear() }
    @Synchronized fun observe(versions: Map<String, Long>) {
        for ((key, version) in versions) values[key] = maxOf(values[key] ?: 0, version)
    }
    @Synchronized fun accept(started: Long, key: String?, rawVersion: String?) {
        if (started != epoch) throw SnapshotSuperseded()
        if (key == null && rawVersion == null) return
        val version = rawVersion?.toLongOrNull()
        require(!key.isNullOrEmpty() && version != null && version >= 0)
        if (version < (values[key] ?: 0)) throw SnapshotSuperseded()
        values[key] = version
    }
}

data class PackageRevision(val packageId: Int, val contentRevision: Long)
fun ActiveEditorOut.packageRevision() = PackageRevision(`package`.id, contentRevision)

private fun transportFailure(error: Exception) = ApiFailure(0, transportIssue = when (error) {
    is java.io.InterruptedIOException -> ApiTransportIssue.TIMEOUT
    is java.net.UnknownHostException -> ApiTransportIssue.DNS
    is javax.net.ssl.SSLException -> ApiTransportIssue.TLS
    is java.net.ProtocolException -> ApiTransportIssue.INVALID_RESPONSE
    is java.io.FileNotFoundException -> ApiTransportIssue.STORAGE
    is IOException -> ApiTransportIssue.CONNECTION
    else -> ApiTransportIssue.INVALID_RESPONSE
})

private val diagnosticIds = AtomicLong()
// Allow only fixed route words. Dynamic identities and all query values stay out of logs.
private val diagnosticSegments = setOf(
    "api", "compat", "pairing", "validate", "me", "dashboard", "activity", "setup", "consent", "accept",
    "settings", "plan", "branding", "assets", "cards", "skip", "meta", "status", "instagram", "token",
    "oauth", "start", "attempts", "select", "packages", "active", "render", "preview", "editor", "order",
    "selections", "media", "remove", "restore", "upload-limits", "uploads", "complete", "resolve",
    "conflicts", "ranges", "reviews", "approve", "reschedule", "occurrences", "push-token",
)

class DojoApi(private val origin: String, private val token: String?, private val versionCode: Int, http: OkHttpClient,
    private val versions: SnapshotVersions = SnapshotVersions(),
    private val diagnostic: (String) -> Unit = { if (BuildConfig.DEBUG) Log.d("DojoHttp", it); Unit }) {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = true }
    private val client = http.newBuilder().followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(10, TimeUnit.SECONDS).callTimeout(30, TimeUnit.SECONDS).build()
    private val readClient = client.newBuilder().retryOnConnectionFailure(true).build()
    // Slow uploads wait for user cancellation, not a transfer deadline. Connection setup stays bounded.
    // Mutations remain non-replayable; the upload engine reconciles acknowledged ranges.
    private val uploadClient = client.newBuilder().writeTimeout(60, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS).callTimeout(180, TimeUnit.SECONDS).build()
    private val waitingUploadClient = uploadClient.newBuilder().writeTimeout(0, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS).callTimeout(0, TimeUnit.SECONDS).build()
    private val waitingUploadReadClient = waitingUploadClient.newBuilder().retryOnConnectionFailure(true).build()

    fun liveEvents(): Flow<LiveEvent> = channelFlow {
        val transport = client.newBuilder().readTimeout(45, TimeUnit.SECONDS).callTimeout(0, TimeUnit.SECONDS).build()
        val request = Request.Builder().url(origin.toHttpUrl().resolve("/api/events")!!)
            .header("X-Android-Version-Code", versionCode.toString()).header("Accept", "text/event-stream")
            .header("Cache-Control", "no-cache")
        token?.let { request.header("Authorization", "Bearer $it") }
        val call = transport.newCall(request.build())
        val worker = launch(Dispatchers.IO) {
            try {
                call.execute().use { response ->
                    if (!response.isSuccessful) throw ApiFailure(response.code)
                    require(response.header("Content-Type")?.substringBefore(';')?.trim()?.lowercase() == "text/event-stream")
                    val body = requireNotNull(response.body)
                    readLiveEvents(body.byteStream()) { send(it) }
                }
                close()
            } catch (error: Exception) { close(error) }
        }
        awaitClose { call.cancel(); worker.cancel() }
    }

    private suspend fun bytes(method: String, path: String, body: RequestBody? = null, authenticated: Boolean = true,
        destination: File? = null, limit: Long = 10L * 1024 * 1024, waitForUpload: Boolean = false,
        packageRevision: PackageRevision? = null): ByteArray {
        val readEpoch = versions.epoch()
        require(path.startsWith("/api/") && !path.contains('\\'))
        val base = origin.toHttpUrl()
        val url = base.resolve(path) ?: throw IllegalArgumentException("path")
        require(url.host == base.host && url.port == base.port && url.scheme == base.scheme && url.encodedPath.startsWith("/api/"))
        val builder = Request.Builder().url(url).header("X-Android-Version-Code", versionCode.toString())
        if (authenticated && token != null) builder.header("Authorization", "Bearer $token")
        packageRevision?.let { builder.header("If-Match", "\"${it.packageId}:${it.contentRevision}\"") }
        builder.method(method, body ?: if (method == "POST" || method == "PUT" || method == "PATCH") ByteArray(0).toRequestBody() else null)
        val transport = when {
            waitForUpload && (path == "/api/media/upload-limits" || path == "/api/media/uploads" || path.startsWith("/api/media/uploads/")) ->
                if (method == "GET") waitingUploadReadClient else waitingUploadClient
            method == "GET" -> readClient
            path == "/api/media/uploads" || path.startsWith("/api/media/uploads/") -> uploadClient
            method == "POST" && path.startsWith("/api/reviews/") && path.endsWith("/approve") ->
                client.newBuilder().readTimeout(120, TimeUnit.SECONDS).callTimeout(120, TimeUnit.SECONDS).build()
            else -> client
        }
        val call = transport.newCall(builder.build())
        val id = diagnosticIds.incrementAndGet()
        val started = System.nanoTime()
        val endpoint = "/" + url.encodedPath.trim('/').split('/').joinToString("/") {
            if (it in diagnosticSegments) it else ":id"
        }
        fun trace(stage: String, status: Int = 0, error: Exception? = null, protocol: String? = null) {
            // Logging must not break requests. Never include exception messages, headers, bodies or URLs.
            runCatching { diagnostic("id=$id $method $endpoint stage=$stage status=$status " +
                "elapsed_ms=${(System.nanoTime() - started) / 1_000_000}" +
                (error?.let { " error=${it.javaClass.simpleName}" } ?: "") +
                (protocol?.let { " protocol=$it" } ?: "")) }
        }
        trace("start")
        return suspendCancellableCoroutine { continuation ->
            continuation.invokeOnCancellation { trace("cancelled"); call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    destination?.delete()
                    if (continuation.isActive) {
                        trace("failed", error = e)
                        continuation.resumeWithException(transportFailure(e))
                    }
                }
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        if (!continuation.isActive) { destination?.delete(); return }
                        try {
                            trace("headers", response.code, protocol = response.protocol.toString())
                            if (!response.isSuccessful) {
                                destination?.delete()
                                val error = runCatching {
                                    val text = response.body?.byteStream()?.use { readBounded(it, 65536).toString(Charsets.UTF_8) }.orEmpty()
                                    json.parseToJsonElement(text).jsonObject
                                }.getOrNull()
                                val update = if (response.code == 426) (error?.get("update_url") as? JsonPrimitive)?.contentOrNull else null
                                val detail = (error?.get("detail") as? JsonPrimitive)?.contentOrNull?.take(1024)
                                val conflict = if (response.code == 409) runCatching {
                                    json.decodeFromJsonElement<EditConflictOut>(error?.get("detail") ?: JsonNull)
                                        .takeIf { it.code == "edit_conflict" && it.contentRevision > 0 && it.conflicts.all { group -> group.key.isNotBlank() } }
                                }.getOrNull() else null
                                val failure = ApiFailure(response.code, update, detail, editConflict = conflict)
                                trace("failed", response.code, failure)
                                continuation.resumeWithException(failure)
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
                                if (continuation.isActive) {
                                    versions.accept(readEpoch, response.header("X-Resource-Key"), response.header("X-Resource-Version"))
                                    trace("end", response.code)
                                    continuation.resume(data)
                                } else destination?.delete()
                            }
                        } catch (e: Exception) {
                            destination?.delete()
                            if (continuation.isActive) {
                                trace("failed", response.code, e)
                                continuation.resumeWithException(if (e is ApiFailure || e is SnapshotSuperseded) e else transportFailure(e))
                            }
                        }
                    }
                }
            })
        }
    }

    suspend fun request(method: String, path: String, body: JsonElement? = null, waitForUpload: Boolean = false,
        packageRevision: PackageRevision? = null): JsonElement {
        val public = path == "/api/compat" || path == "/api/pairing/validate"
        var retries = 0
        while (true) {
            try {
                val data = bytes(method, path, body?.toString()?.toRequestBody("application/json".toMediaType()), !public, waitForUpload = waitForUpload, packageRevision = packageRevision)
                return try { if (data.isEmpty()) JsonNull else json.parseToJsonElement(data.toString(Charsets.UTF_8)) }
                catch (_: SerializationException) { throw SerializationException("Invalid server response") }
            } catch (e: ApiFailure) {
                // OkHttp connection recovery does not cover read timeouts after a request was sent.
                if (method != "GET" || e.status != 0 || retries == 2) throw e
                delay(250L shl retries++)
            }
        }
    }
    private inline fun <reified T> decode(value: JsonElement): T = try { json.decodeFromJsonElement<T>(value) }
        catch (_: SerializationException) { throw SerializationException("Invalid server response") }

    suspend fun compat(): CompatInfo = decode(request("GET", "/api/compat"))
    suspend fun pair(code: String, name: String): PairingOut = decode(request("POST", "/api/pairing/validate", json.encodeToJsonElement(ValidateIn(code, "device", name))))
    suspend fun me(): ClientOut = decode(request("GET", "/api/pairing/me"))
    suspend fun dashboard(): DashboardOut = decode(request("GET", "/api/dashboard"))
    suspend fun activity(): ActivityPageOut = decode(request("GET", "/api/activity?limit=50"))
    suspend fun setup(): SetupOut = decode(request("GET", "/api/setup"))
    suspend fun review(id: Int): ReviewDetailOut = decode(request("GET", "/api/reviews/$id"))
    private suspend fun reviewDecision(id: Int, action: String, body: JsonElement): JsonObject =
        request("POST", "/api/reviews/$id/$action", body) as? JsonObject ?: throw SerializationException("Invalid review response")
    suspend fun approveReview(id: Int, version: Int): JsonObject = reviewDecision(id, "approve", json.encodeToJsonElement(ApproveIn(version)))
    suspend fun skipReview(id: Int, version: Int): JsonObject = reviewDecision(id, "skip", json.encodeToJsonElement(SkipIn(confirmed = true, version = version)))
    suspend fun rescheduleReview(id: Int, version: Int, newDueAt: String): JsonObject = reviewDecision(id, "reschedule", json.encodeToJsonElement(RescheduleIn(newDueAt, version)))
    suspend fun skipEmptyOccurrence(id: Int, body: EmptySkipIn): OccurrenceDecisionOut = decode(request("POST", "/api/reviews/occurrences/$id/skip", json.encodeToJsonElement(body)))
    suspend fun rescheduleEmptyOccurrence(id: Int, body: EmptyRescheduleIn): OccurrenceDecisionOut = decode(request("POST", "/api/reviews/occurrences/$id/reschedule", json.encodeToJsonElement(body)))
    suspend fun renderPackage(folder: String, expected: PackageRevision, retry: Boolean = false): RenderOut = decode(request("POST", "/api/packages/active/render", json.encodeToJsonElement(RenderIn(expectedFolderName = folder, retry = retry)), packageRevision = expected))
    suspend fun registerPushToken(token: String) { request("PUT", "/api/pairing/me/push-token", json.encodeToJsonElement(PushTokenIn(token))) }
    suspend fun removePushToken() { request("DELETE", "/api/pairing/me/push-token") }
    suspend fun downloadReviewPreview(path: String, destination: File, limit: Long = 512L * 1024 * 1024) {
        try { bytes("GET", path, destination = destination, limit = limit) }
        catch (e: Exception) { destination.delete(); throw e }
    }
    suspend fun consent(): ConsentOut = decode(request("GET", "/api/setup/consent"))
    suspend fun acceptConsent(version: Int): AcceptanceOut = decode(request("POST", "/api/setup/consent/accept", buildJsonObject { put("version", version) }))
    suspend fun plan(): PlanOut = decode(request("GET", "/api/settings/plan"))
    suspend fun savePlan(body: PlanIn): PlanOut = decode(request("PUT", "/api/settings/plan", json.encodeToJsonElement(body)))
    suspend fun reminders(): ReminderPolicyOut = decode(request("GET", "/api/settings/reminders"))
    suspend fun saveReminders(body: ReminderPolicyIn): ReminderPolicyOut = decode(request("PUT", "/api/settings/reminders", json.encodeToJsonElement(body)))
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
    suspend fun mediaEditor(): ActiveEditorOut = decode(request("GET", "/api/packages/active/editor"))
    suspend fun savePackageEdits(body: PackageEditIn): ActiveEditorOut = decode(request("PUT", "/api/packages/active/edits", json.encodeToJsonElement(body)))
    suspend fun orderMedia(folder: String, order: List<String>, expected: PackageRevision) = request("PUT", "/api/packages/active/order",
        json.encodeToJsonElement(OrderIn(expectedFolderName = folder, order = order)), packageRevision = expected)
    suspend fun selectVideoRanges(folder: String, selections: Map<String, List<VideoRangeOut>>, expected: PackageRevision) = request("PUT", "/api/packages/active/selections",
        json.encodeToJsonElement(SelectionIn(expectedFolderName = folder, selections = selections)), packageRevision = expected)
    suspend fun removeMedia(folder: String, id: String, expected: PackageRevision) = request("POST", "/api/packages/active/media/${segment(id)}/remove?expected_folder_name=${segment(folder)}", packageRevision = expected)
    suspend fun restoreMedia(folder: String, id: String, expected: PackageRevision) = request("POST", "/api/packages/active/media/${segment(id)}/restore?expected_folder_name=${segment(folder)}", packageRevision = expected)
    suspend fun uploadLimits(): UploadLimitsOut = decode(request("GET", "/api/media/upload-limits", waitForUpload = true))
    suspend fun startUpload(body: UploadInitIn): UploadOut = decode(request("POST", "/api/media/uploads", json.encodeToJsonElement(body), waitForUpload = true))
    suspend fun uploadStatus(id: String, waitForUpload: Boolean = false): UploadOut = decode(request("GET", "/api/media/uploads/${segment(id)}", waitForUpload = waitForUpload))
    suspend fun completeUpload(id: String): UploadOut = decode(request("POST", "/api/media/uploads/${segment(id)}/complete", waitForUpload = true))
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
            bytes.toRequestBody("application/octet-stream".toMediaType()), waitForUpload = true)
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
