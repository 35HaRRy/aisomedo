package com.dojo.aisomedo.notifications

import android.app.NotificationManager
import android.content.Context
import com.dojo.aisomedo.BuildConfig
import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.SessionCredential
import com.dojo.aisomedo.uploads.UploadRuntime
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailabilityLight
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.OkHttpClient

class PushRuntime private constructor(private val context: Context) {
    private val store = UploadRuntime.get(context).sessionStore
    private val notifications = ReviewNotifications(context)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val http = OkHttpClient()
    private val mutableAvailability = MutableStateFlow(PushAvailability.UNCONFIGURED)
    private val registration = PushRegistration(store, http, BuildConfig.VERSION_CODE, scope)
    val failure = registration.failure
    val availability = combine(mutableAvailability, registration.ready, failure, ::registrationAvailability)
        .stateIn(scope, SharingStarted.Eagerly, PushAvailability.UNCONFIGURED)
    private val mutableReceipts = MutableSharedFlow<PushReceipt>(extraBufferCapacity = 1)
    val receipts = mutableReceipts.asSharedFlow()
    private var epoch = 0
    private var session: Pair<String, SessionCredential>? = null
    private var latestToken: String? = null
    init {
        context.cacheDir.resolve("review-previews").listFiles()?.filter { it.isFile }?.forEach { it.delete() }
    }
    private fun captured(): Pair<String, SessionCredential>? = runCatching {
        val origin = store.origin ?: return null
        origin to (store.readSession(origin) ?: return null)
    }.getOrNull()
    private fun matches(origin: String, binding: String) = runCatching { store.origin == origin && store.readSession(origin)?.bindingId == binding }.getOrDefault(false)
    @Synchronized fun refresh(token: String? = null) {
        val next = captured()
        if (session?.first != next?.first || session?.second?.bindingId != next?.second?.bindingId) {
            if (next == null) registration.stopSession()
            epoch++; notifications.clear()
        }
        session = next
        val messaging = runCatching { FirebaseApp.getInstance(); FirebaseMessaging.getInstance() }.getOrNull()
        if (messaging == null) { mutableAvailability.value = PushAvailability.UNCONFIGURED; return }
        if (GoogleApiAvailabilityLight.getInstance().isGooglePlayServicesAvailable(context) != ConnectionResult.SUCCESS) {
            mutableAvailability.value = PushAvailability.SERVICES_UNAVAILABLE; return
        }
        val manager = context.getSystemService(NotificationManager::class.java)
        val allowed = manager.areNotificationsEnabled() && manager.getNotificationChannel("dojo-reviews")?.importance != NotificationManager.IMPORTANCE_NONE
        mutableAvailability.value = if (allowed) PushAvailability.AVAILABLE else PushAvailability.PERMISSION_DENIED
        if (next == null) { messaging.isAutoInitEnabled = false; return }
        val (origin, credential) = next
        val current = epoch
        messaging.isAutoInitEnabled = true
        if (token != null) latestToken = token
        if (latestToken == null) {
            messaging.token.addOnCompleteListener { result ->
                synchronized(this) {
                    if (epoch != current || !matches(origin, credential.bindingId)) return@addOnCompleteListener
                    if (result.isSuccessful) refresh(result.result) else mutableAvailability.value = PushAvailability.REGISTRATION_FAILED
                }
            }
            return
        }
        registration.refresh(latestToken!!)
    }
    fun receive(data: Map<String, String>) {
        val target = parseNotificationTarget(data) ?: return
        val (origin, credential) = captured() ?: return
        if (!matches(origin, credential.bindingId)) return
        notifications.show(target, data["title"].orEmpty(), data["body"].orEmpty(), credential.bindingId)
        mutableReceipts.tryEmit(PushReceipt(origin, credential.bindingId))
    }
    @Synchronized fun stopSession() {
        epoch++; registration.stopSession()
        session = null; notifications.clear()
        runCatching { FirebaseMessaging.getInstance().isAutoInitEnabled = false }
    }
    companion object {
        @Volatile private var instance: PushRuntime? = null
        fun get(context: Context): PushRuntime = instance ?: synchronized(this) {
            instance ?: PushRuntime(context.applicationContext).also { instance = it }
        }
    }
}
