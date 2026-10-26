package com.dojo.aisomedo.notifications

import com.dojo.aisomedo.api.*
import com.dojo.aisomedo.auth.*
import com.dojo.aisomedo.offline.SnapshotStore
import com.dojo.aisomedo.safeExternalUrl
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import okhttp3.OkHttpClient

/** Session-bound registration owns HTTP retries and deduplication, not Firebase or Android lifecycle. */
internal class PushRegistration(private val store: SessionStore, private val http: OkHttpClient,
    private val versionCode: Int, private val scope: CoroutineScope,
    private val snapshots: SnapshotStore? = null,
    private val allowed: (String, String) -> Boolean = { _, _ -> true },
    private val onSessionFailure: (PushFailure) -> Unit = {}) {
    private val mutableFailure = MutableStateFlow<PushFailure?>(null)
    val failure = mutableFailure.asStateFlow()
    private val mutableReady = MutableStateFlow(false)
    val ready = mutableReady.asStateFlow()
    private var session: Pair<String, SessionCredential>? = null
    private var registered: Triple<String, String, String>? = null
    private var latestToken: String? = null
    private var epoch = 0
    private var job: Job? = null
    val busy: Boolean @Synchronized get() = job?.isActive == true
    private fun captured(): Pair<String, SessionCredential>? = runCatching {
        val origin = store.origin ?: return null
        origin to (store.readSession(origin) ?: return null)
    }.getOrNull()
    private fun matches(origin: String, binding: String) = runCatching { store.origin == origin && store.readSession(origin)?.bindingId == binding }.getOrDefault(false)
    @Synchronized fun refresh(token: String) {
        val next = captured()
        if (session?.first != next?.first || session?.second?.bindingId != next?.second?.bindingId) reset(session)
        session = next
        latestToken = token
        if (next == null || token.isBlank()) return
        val (origin, credential) = next
        if (!allowed(origin, credential.bindingId)) return
        val identity = Triple(origin, credential.bindingId, token)
        if (registered == identity || busy) return
        mutableReady.value = false
        val current = epoch
        job = scope.launch(start = CoroutineStart.LAZY) {
            try {
                if (!matches(origin, credential.bindingId) || !allowed(origin, credential.bindingId)) return@launch
                DojoApi(origin, credential.token, versionCode, http).registerPushToken(token)
                synchronized(this@PushRegistration) {
                    if (epoch == current && matches(origin, credential.bindingId)) { registered = identity; mutableFailure.value = null; mutableReady.value = true }
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                val rejection = synchronized(this@PushRegistration) {
                    if (epoch != current || !matches(origin, credential.bindingId)) null else {
                        val error = e as? ApiFailure
                        PushFailure(origin, credential.bindingId, error?.status ?: 0, error?.updateUrl)
                    }
                }
                if (rejection != null) {
                    if (rejection.status in setOf(401, 426)) synchronized(store) {
                        if (matches(origin, credential.bindingId)) {
                            if (rejection.status == 426) runCatching { snapshots?.update(origin) {
                                it.copy(rejectedVersionCode = versionCode, updateUrl = safeExternalUrl(rejection.updateUrl.orEmpty()) ?: it.updateUrl)
                            } }
                            onSessionFailure(rejection)
                        }
                    }
                    synchronized(this@PushRegistration) {
                        if (epoch == current && matches(origin, credential.bindingId)) mutableFailure.value = rejection
                    }
                }
            } finally { synchronized(this@PushRegistration) {
                if (epoch == current) {
                    job = null
                    latestToken?.takeIf { it != token && matches(origin, credential.bindingId) }?.let { refresh(it) }
                }
            } }
        }.also { it.start() }
    }
    @Synchronized fun stopSession() {
        reset(session ?: captured())
    }
    private fun reset(previous: Pair<String, SessionCredential>?) {
        epoch++; job?.cancel(); job = null
        previous?.let { old -> scope.launch { runCatching {
            if (allowed(old.first, old.second.bindingId))
                withTimeout(5000) { DojoApi(old.first, old.second.token, versionCode, http).removePushToken() }
        } } }
        session = null; registered = null; latestToken = null; mutableFailure.value = null; mutableReady.value = false
    }
}
