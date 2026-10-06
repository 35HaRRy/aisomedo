package com.dojo.aisomedo.api

import java.net.URI
import java.util.Locale

/** Hand-written client configuration; generatedCompat types live in GeneratedApi.kt. */
object ApiConfig {
    /** Emulator loopback to the host backend. Override per build flavor later. */
    const val BASE_URL = "http://10.0.2.2:8000"

    fun compatUrl(baseUrl: String = BASE_URL): String = "$baseUrl/api/compat"

    fun normalizeOrigin(raw: String, allowHttp: Boolean): String {
        val uri = try { URI(raw.trim()) } catch (_: Exception) { throw IllegalArgumentException("origin") }
        val scheme = uri.scheme?.lowercase(Locale.ROOT)
        require(scheme == "https" || (allowHttp && scheme == "http"))
        require(!uri.host.isNullOrBlank() && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null)
        require(uri.rawPath.isNullOrEmpty() || uri.rawPath == "/")
        require(uri.port == -1 || uri.port in 1..65535)
        val port = if (uri.port == -1 || (scheme == "https" && uri.port == 443) || (scheme == "http" && uri.port == 80)) "" else ":${uri.port}"
        return "$scheme://${uri.host.lowercase(Locale.ROOT)}$port"
    }

    /** Every authenticated device call must carry the installed version code. */
    fun deviceHeaders(token: String, versionCode: Int): Map<String, String> = mapOf(
        "Authorization" to "Bearer $token",
        ApiContract.VERSION_HEADER to versionCode.toString(),
    )
}
