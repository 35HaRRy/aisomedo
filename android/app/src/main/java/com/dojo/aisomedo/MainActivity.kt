package com.dojo.aisomedo

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.dojo.aisomedo.auth.*
import com.dojo.aisomedo.ui.DojoApp
import okhttp3.OkHttpClient

class MainActivity : ComponentActivity() {
    private lateinit var model: AppViewModel
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        model = ViewModelProvider(this, viewModelFactory {
            initializer {
                AppViewModel(SessionStore(noBackupFilesDir.resolve("session")) { androidKeystoreKey() },
                    OkHttpClient(), packageManager.getPackageInfo(packageName, 0).longVersionCode.toInt(),
                    BuildConfig.DEBUG, createSavedStateHandle())
            }
        })[AppViewModel::class.java]
        setContent { DojoApp(model, ::openUrl) }
    }
    override fun onStart() { super.onStart(); if (::model.isInitialized) model.refresh() }
    private fun openUrl(url: String) {
        val safe = safeExternalUrl(url) ?: return
        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(safe))) }
        catch (_: Exception) { Toast.makeText(this, R.string.browser_unavailable, Toast.LENGTH_LONG).show() }
    }
}
