// GENERATED from backend/openapi.json — do not edit by hand.
// Regenerate: uv run --project backend python backend/scripts/generate_clients.py
package com.dojo.aisomedo.api

object ApiContract {
    const val CONTRACT_VERSION = "0.1.0"
    const val VERSION_HEADER = "X-Android-Version-Code"
}

data class CompatInfo(
    val apiVersion: String,
    val androidMinVersionCode: Int,
    val androidCurrentVersionCode: Int,
    val updateUrl: String,
)

object UpdatePolicy {
    fun isOutdated(installedVersionCode: Int, minVersionCode: Int): Boolean =
        installedVersionCode < minVersionCode
}
