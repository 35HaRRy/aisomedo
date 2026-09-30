package com.dojo.aisomedo

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.dojo.aisomedo.api.ApiConfig
import com.dojo.aisomedo.api.CompatInfo
import com.dojo.aisomedo.api.UpdatePolicy
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val status = TextView(this).apply { text = "Dojo Yayıncılık — sürüm denetleniyor…" }
        setContentView(status)
        Thread { checkCompatibility(status) }.start()
    }

    private fun checkCompatibility(status: TextView) {
        val compat = fetchCompat()
        runOnUiThread {
            if (compat == null) {
                status.text = "Dojo Yayıncılık (çevrimdışı — sunucuya ulaşılamadı)"
                return@runOnUiThread
            }
            if (UpdatePolicy.isOutdated(installedVersionCode(), compat.androidMinVersionCode)) {
                showUpdateScreen(compat)
            } else {
                status.text = "Dojo Yayıncılık"
            }
        }
    }

    private fun installedVersionCode(): Int {
        return packageManager.getPackageInfo(packageName, 0).longVersionCode.toInt()
    }

    private fun fetchCompat(): CompatInfo? {
        return try {
            val connection = URL(ApiConfig.compatUrl()).openConnection() as HttpURLConnection
            try {
                connection.connectTimeout = 8000
                connection.readTimeout = 8000
                if (connection.responseCode != 200) return null
                val body = connection.inputStream.bufferedReader().readText()
                val json = JSONObject(body)
                CompatInfo(
                    apiVersion = json.getString("api_version"),
                    androidMinVersionCode = json.getInt("android_min_version_code"),
                    androidCurrentVersionCode = json.getInt("android_current_version_code"),
                    updateUrl = json.getString("update_url"),
                )
            } finally {
                connection.disconnect()
            }
        } catch (e: Exception) {
            null
        }
    }

    private fun showUpdateScreen(compat: CompatInfo) {
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
        }
        val message = TextView(this).apply {
            text = "Yeni bir Dojo sürümü gerekli (sunucu en az ${compat.androidMinVersionCode} istiyor). " +
                "Devam etmek için güncellemeyi yükleyin."
        }
        val button = Button(this).apply {
            text = "Güncellemeyi indir"
            setOnClickListener {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(compat.updateUrl)))
            }
        }
        layout.addView(message)
        layout.addView(button)
        setContentView(layout)
    }
}
