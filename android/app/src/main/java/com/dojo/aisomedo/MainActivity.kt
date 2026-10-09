package com.dojo.aisomedo

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
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
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.combine
import okhttp3.OkHttpClient

class MainActivity : ComponentActivity() {
    private lateinit var model: AppViewModel
    private lateinit var uploads: UploadRuntime
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        uploads = UploadRuntime.get(this)
        model = ViewModelProvider(this, viewModelFactory {
            initializer {
                AppViewModel(uploads.sessionStore,
                    OkHttpClient(), packageManager.getPackageInfo(packageName, 0).longVersionCode.toInt(),
                    BuildConfig.DEBUG, createSavedStateHandle(), uploads::stopSession)
            }
        })[AppViewModel::class.java]
        var packageRequested = intent.getStringExtra("destination") == "PACKAGE"
        lifecycleScope.launch { repeatOnLifecycle(Lifecycle.State.STARTED) {
            launch { model.state.collect { state ->
                if (state.phase == Phase.READY) {
                    state.client?.let { uploads.attach(state.origin, it.id) }
                    if (packageRequested) { packageRequested = false; model.navigate(Destination.PACKAGE) }
                }
            } }
            launch { uploads.issue.collect { issue -> if (issue != null) model.observeSessionFailure(issue, uploads.failureBinding) } }
            launch {
                var observed = emptySet<String>()
                combine(uploads.rows, model.state) { rows, state -> rows to state }.collect { (rows, state) ->
                    if (state.phase == Phase.READY && !state.busy) {
                        val transitions = rows.flatMap { row -> listOfNotNull(row.status?.uploadId?.let { "init:$it" }, if (row.phase == UploadPhase.FINALIZED) "final:${row.id}" else null) }.toSet()
                        if ((transitions - observed).isNotEmpty()) { observed = transitions; model.refresh() }
                    }
                }
            }
        } }
        setContent { DojoApp(model, uploads, ::openUrl) }
    }
    override fun onStart() {
        super.onStart()
        if (::model.isInitialized) {
            model.refresh()
            lifecycleScope.launch { uploads.refresh() }
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getStringExtra("destination") == "PACKAGE") model.navigate(Destination.PACKAGE)
    }
    private fun openUrl(url: String) {
        val safe = safeExternalUrl(url) ?: return
        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(safe))) }
        catch (_: Exception) { Toast.makeText(this, R.string.browser_unavailable, Toast.LENGTH_LONG).show() }
    }
}
