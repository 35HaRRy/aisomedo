// GENERATED from backend/openapi.json — do not edit by hand.
// Regenerate: uv run --project backend python backend/scripts/generate_clients.py
package com.dojo.aisomedo.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

object ApiContract {
    const val CONTRACT_VERSION = "0.1.0"
    const val VERSION_HEADER = "X-Android-Version-Code"
}

object UpdatePolicy {
    fun isOutdated(installedVersionCode: Int, minVersionCode: Int): Boolean =
        installedVersionCode < minVersionCode
}

@Serializable
data class AcceptanceIn(
    @SerialName("version") val version: Int? = null,
)

@Serializable
data class AcceptanceOut(
    @SerialName("accepted_at") val acceptedAt: String,
    @SerialName("version") val version: Int,
)

@Serializable
data class AttemptOut(
    @SerialName("candidates") val candidates: List<MetaCandidateOut>,
    @SerialName("id") val id: String,
    @SerialName("status") val status: String,
)

@Serializable
data class BrandingAssetOut(
    @SerialName("asset") val asset: String,
    @SerialName("preview_url") val previewUrl: String,
)

@Serializable
data class BrandingDefaultsOut(
    @SerialName("caption_template") val captionTemplate: String?,
    @SerialName("intro_asset") val introAsset: String?,
    @SerialName("intro_duration") val introDuration: Double?,
    @SerialName("logo_asset") val logoAsset: String?,
    @SerialName("outro_asset") val outroAsset: String?,
    @SerialName("outro_duration") val outroDuration: Double?,
)

@Serializable
data class ClientOut(
    @SerialName("created_at") val createdAt: String,
    @SerialName("created_by") val createdBy: String,
    @SerialName("id") val id: Int,
    @SerialName("kind") val kind: String,
    @SerialName("last_seen_at") val lastSeenAt: String?,
    @SerialName("name") val name: String,
    @SerialName("revoked_at") val revokedAt: String?,
)

@Serializable
data class CompatInfo(
    @SerialName("api_version") val apiVersion: String,
    @SerialName("android_min_version_code") val androidMinVersionCode: Int,
    @SerialName("android_current_version_code") val androidCurrentVersionCode: Int,
    @SerialName("update_url") val updateUrl: String,
)

@Serializable
data class ConsentOut(
    @SerialName("accepted_at") val acceptedAt: String?,
    @SerialName("text") val text: String,
    @SerialName("version") val version: Int,
)

@Serializable
data class DashboardActionOut(
    @SerialName("due_at") val dueAt: String,
    @SerialName("occurrence_id") val occurrenceId: Int,
    @SerialName("package_folder") val packageFolder: String?,
    @SerialName("review_id") val reviewId: Int?,
    @SerialName("state") val state: String,
    @SerialName("version") val version: Int?,
)

@Serializable
data class DashboardInstagramOut(
    @SerialName("health") val health: String,
    @SerialName("username") val username: String? = null,
)

@Serializable
data class DashboardOut(
    @SerialName("generated_at") val generatedAt: String,
    @SerialName("instagram") val instagram: DashboardInstagramOut,
    @SerialName("next_slot") val nextSlot: DashboardSlotOut?,
    @SerialName("package") val `package`: PackageOut?,
    @SerialName("pending_actions") val pendingActions: List<DashboardActionOut>,
    @SerialName("plan") val plan: PlanOut,
    @SerialName("worker") val worker: DashboardWorkerOut,
)

@Serializable
data class DashboardSlotOut(
    @SerialName("due_at") val dueAt: String,
    @SerialName("kind") val kind: String,
)

@Serializable
data class DashboardWorkerOut(
    @SerialName("phase") val phase: String?,
    @SerialName("status") val status: String,
)

@Serializable
data class MetaCandidateOut(
    @SerialName("ig_user_id") val igUserId: String,
    @SerialName("ig_username") val igUsername: String,
    @SerialName("page_id") val pageId: String? = null,
    @SerialName("page_name") val pageName: String? = null,
)

@Serializable
data class PackageOut(
    @SerialName("created_at") val createdAt: String,
    @SerialName("folder_name") val folderName: String,
    @SerialName("id") val id: Int,
    @SerialName("status") val status: String,
)

@Serializable
data class PairingOut(
    @SerialName("client_id") val clientId: Int,
    @SerialName("kind") val kind: String,
    @SerialName("token") val token: String? = null,
)

@Serializable
data class PlanIn(
    @SerialName("anchor_date") val anchorDate: String? = null,
    @SerialName("anchor_time") val anchorTime: String? = null,
    @SerialName("enabled") val enabled: Boolean = true,
)

@Serializable
data class PlanOut(
    @SerialName("anchor_date") val anchorDate: String?,
    @SerialName("anchor_time") val anchorTime: String?,
    @SerialName("enabled") val enabled: Boolean,
    @SerialName("timezone") val timezone: String,
)

@Serializable
data class SelectIn(
    @SerialName("ig_user_id") val igUserId: String,
)

@Serializable
data class SetupItemOut(
    @SerialName("complete") val complete: Boolean,
    @SerialName("key") val key: String,
    @SerialName("label") val label: String,
    @SerialName("required") val required: Boolean = true,
)

@Serializable
data class SetupOut(
    @SerialName("checklist") val checklist: List<SetupItemOut>,
    @SerialName("ready") val ready: Boolean,
)

@Serializable
data class StartIn(
    @SerialName("return_uri") val returnUri: String? = null,
)

@Serializable
data class StartOut(
    @SerialName("attempt_id") val attemptId: String,
    @SerialName("auth_url") val authUrl: String,
)

@Serializable
data class StatusOut(
    @SerialName("connection_type") val connectionType: String = "facebook_login",
    @SerialName("expires_at") val expiresAt: String? = null,
    @SerialName("health") val health: String,
    @SerialName("ig_user_id") val igUserId: String? = null,
    @SerialName("ig_username") val igUsername: String? = null,
    @SerialName("last_checked_at") val lastCheckedAt: String? = null,
    @SerialName("last_error") val lastError: String? = null,
    @SerialName("last_refreshed_at") val lastRefreshedAt: String? = null,
    @SerialName("page_id") val pageId: String? = null,
    @SerialName("page_name") val pageName: String? = null,
)

@Serializable
data class UploadInitIn(
    @SerialName("content_type") val contentType: String,
    @SerialName("declared_size_bytes") val declaredSizeBytes: Long,
    @SerialName("expected_package_id") val expectedPackageId: Int? = null,
    @SerialName("filename") val filename: String,
)

@Serializable
data class UploadLimitsOut(
    @SerialName("active_package_id") val activePackageId: Int? = null,
    @SerialName("max_file_bytes") val maxFileBytes: Long,
    @SerialName("max_package_bytes") val maxPackageBytes: Long,
)

@Serializable
data class UploadOut(
    @SerialName("conflicts") val conflicts: List<Map<String, JsonElement>> = emptyList(),
    @SerialName("declared_size_bytes") val declaredSizeBytes: Long,
    @SerialName("error_reason") val errorReason: String? = null,
    @SerialName("package_id") val packageId: Int? = null,
    @SerialName("received_bytes") val receivedBytes: Long,
    @SerialName("received_ranges") val receivedRanges: List<List<Long>>,
    @SerialName("status") val status: String,
    @SerialName("upload_id") val uploadId: String,
)

@Serializable
data class ValidateIn(
    @SerialName("code") val code: String,
    @SerialName("kind") val kind: String,
    @SerialName("name") val name: String,
)
