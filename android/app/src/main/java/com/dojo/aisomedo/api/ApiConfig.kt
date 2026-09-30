package com.dojo.aisomedo.api

/** Hand-written client configuration; generatedCompat types live in GeneratedApi.kt. */
object ApiConfig {
    /** Emulator loopback to the host backend. Override per build flavor later. */
    const val BASE_URL = "http://10.0.2.2:8000"

    fun compatUrl(baseUrl: String = BASE_URL): String = "$baseUrl/api/compat"

    /** Every authenticated device call must carry the installed version code. */
    fun deviceHeaders(token: String, versionCode: Int): Map<String, String> = mapOf(
        "Authorization" to "Bearer $token",
        ApiContract.VERSION_HEADER to versionCode.toString(),
    )
}
