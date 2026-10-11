package com.dojo.aisomedo

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.Manifest
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.dojo.aisomedo.auth.*
import com.dojo.aisomedo.ui.DojoApp
import com.dojo.aisomedo.uploads.*
import com.dojo.aisomedo.notifications.*
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.combine
import okhttp3.OkHttpClient

class MainActivity : ComponentActivity() {
    private lateinit var model: AppViewModel
    private lateinit var uploads: UploadRuntime
    private lateinit var push: PushRuntime
    private var packageRequested = false
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { if (::push.isInitialized) push.refresh() }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        uploads = UploadRuntime.get(this)
        push = PushRuntime.get(this)
        model = ViewModelProvider(this, viewModelFactory {
            initializer {
                AppViewModel(uploads.sessionStore,
                    OkHttpClient(), packageManager.getPackageInfo(packageName, 0).longVersionCode.toInt(),
                    BuildConfig.DEBUG, createSavedStateHandle()) { uploads.stopSession(); push.stopSession() }
            }
        })[AppViewModel::class.java]
        handleIntent(intent)
        lifecycleScope.launch { repeatOnLifecycle(Lifecycle.State.STARTED) {
            launch {
                var attached: Pair<String, Int>? = null
                model.state.collect { state ->
                if (state.phase == Phase.READY) {
                    state.client?.let { uploads.attach(state.origin, it.id) }
                    if (packageRequested) { packageRequested = false; model.navigate(Destination.PACKAGE) }
                    val next = state.origin to (state.client?.id ?: 0)
                    if (attached != next) { attached = next; push.refresh() }
                    if (state.review.issue == com.dojo.aisomedo.reviews.ReviewIssue.ALREADY_HANDLED) {
                        state.review.target?.reviewId?.let { ReviewNotifications(this@MainActivity).cancelReview(it) }
                        state.review.target?.occurrenceId?.let { ReviewNotifications(this@MainActivity).cancelOccurrence(it) }
                    }
                }
            } }
            launch { uploads.issue.collect { issue -> if (issue != null) model.observeSessionFailure(issue, uploads.failureBinding) } }
            launch { push.failure.collect { failure -> failure?.let(model::observePushFailure) } }
            launch {
                var observed = emptySet<String>()
                combine(uploads.rows, model.state) { rows, state -> rows to state }.collect { (rows, state) ->
                    if (state.phase == Phase.READY && !state.busy) {
                        val transitions = rows.flatMap { row -> listOfNotNull(row.status?.uploadId?.let { "init:$it" }, if (row.phase == UploadPhase.FINALIZED) "final:${row.id}" else null) }.toSet()
                        if ((transitions - observed).isNotEmpty()) {
                            observed = transitions; model.refresh()
                            if (state.review.target != null) model.refreshReview()
                        }
                    }
                }
            }
        } }
        setContent { DojoApp(model, uploads, push, {
            if (Build.VERSION.SDK_INT >= 33) notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            else openNotificationSettings()
        }, ::openNotificationSettings, ::openUrl) }
    }
    override fun onStart() {
        super.onStart()
        if (::model.isInitialized) {
            model.refresh()
            lifecycleScope.launch { uploads.refresh() }
            push.refresh()
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }
    private fun handleIntent(intent: Intent) {
        if (intent.getStringExtra("destination") == "PACKAGE") {
            packageRequested = true
            if (model.state.value.phase == Phase.READY) { packageRequested = false; model.navigate(Destination.PACKAGE) }
        }
        val data = runCatching { intent.extras?.keySet()?.mapNotNull { key -> intent.getStringExtra(key)?.let { key to it } }?.toMap() }.getOrNull() ?: return
        val target = parseNotificationTarget(data) ?: return
        val origin = data["notification_origin"] ?: uploads.sessionStore.origin ?: return
        val binding = data["notification_binding"] ?: runCatching { uploads.sessionStore.readSession(origin)?.bindingId }.getOrNull() ?: return
        model.openNotification(target, origin, binding)
        // Rotation/process recreation uses SavedState, never consumes launcher extras twice.
        data.keys.filter { it == "type" || it.startsWith("notification_") }.forEach(intent::removeExtra)
    }
    private fun openNotificationSettings() {
        startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName))
    }
    private fun openUrl(url: String) {
        val safe = safeExternalUrl(url) ?: return
        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(safe))) }
        catch (_: Exception) { Toast.makeText(this, R.string.browser_unavailable, Toast.LENGTH_LONG).show() }
    }
}
