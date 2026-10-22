package com.dojo.aisomedo.live

import com.dojo.aisomedo.api.ApiFailure
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlin.random.Random

enum class LivePhase { CONNECTING, SYNCING, LIVE, DISCONNECTED, UNAUTHORIZED }

/** One foreground stream and one coalesced snapshot reader; no data-read timer. */
class LiveCoordinator(
    private val scope: CoroutineScope,
    private val events: () -> Flow<LiveEvent>,
    private val refresh: suspend (Set<String>) -> Unit,
    private val onFailure: suspend (ApiFailure) -> Unit = {},
    private val onChange: (Map<String, Long>) -> Unit = {},
) {
    private val mutable = MutableStateFlow(LivePhase.CONNECTING)
    val phase: StateFlow<LivePhase> = mutable.asStateFlow()
    private var foreground = false
    private var terminal = false
    private var stream: Job? = null
    private var reader: Job? = null
    private var ready = false
    private var epoch = 0
    private val pending = mutableSetOf<String>()
    private val required = mutableSetOf<String>()
    private val versions = mutableMapOf<String, Long>()

    fun setForeground(active: Boolean) {
        if (foreground == active) return
        foreground = active
        if (!active) { disconnect(); stream?.cancel(); stream = null; return }
        if (terminal) return
        mutable.value = LivePhase.CONNECTING
        stream = scope.launch {
            var attempt = 0
            while (isActive && foreground && !terminal) {
                try {
                    coroutineScope {
                    val messages = events().produceIn(this)
                    try { while (isActive) {
                        val event = withTimeoutOrNull(45_000) { messages.receive() } ?: throw ApiFailure(0)
                        when (event.type) {
                            "ready" -> {
                                require(event.protocol == 1 && !ready)
                                ready = true; invalidate(setOf("*"))
                            }
                            "heartbeat" -> { require(ready); attempt = 0 }
                            "change" -> {
                                require(ready && !event.eventId.isNullOrBlank() && event.eventId.length <= 128)
                                val changed = event.versions.filter { (key, version) ->
                                    require(key.isNotEmpty() && key.length <= 255 && version > 0)
                                    version > (versions[key] ?: 0)
                                }
                                versions.putAll(changed); onChange(changed); invalidate(changed.keys)
                            }
                            "resync" -> throw ApiFailure(if (event.reason == "unauthorized") 401 else 0)
                        }
                    } } finally { messages.cancel() }
                    }
                } catch (error: CancellationException) { throw error }
                catch (error: Exception) {
                    if (error is ApiFailure && error.status in setOf(401, 426)) terminal = true
                    if (error is ApiFailure && error.status == 401) mutable.value = LivePhase.UNAUTHORIZED
                    if (error is ApiFailure && terminal) onFailure(error)
                } finally { disconnect() }
                if (terminal) break
                delay((minOf(30_000.0, 1_000.0 * (1L shl minOf(attempt++, 5))) * Random.nextDouble(0.8, 1.2)).toLong().coerceAtMost(30_000))
            }
        }
    }

    private fun disconnect() {
        epoch++; ready = false
        reader?.cancel(); reader = null; pending.clear(); required.clear()
        if (mutable.value != LivePhase.UNAUTHORIZED) mutable.value = LivePhase.DISCONNECTED
    }

    fun invalidate(resources: Set<String>) {
        if (!ready || resources.isEmpty()) return
        pending.addAll(resources)
        mutable.value = LivePhase.SYNCING
        if (reader != null) return
        val current = epoch
        reader = scope.launch {
            try {
                while (pending.isNotEmpty() || required.isNotEmpty()) {
                    val next = (pending + required).toSet(); pending.clear()
                    try { refresh(next); ensureActive(); required.removeAll(next) }
                    catch (error: CancellationException) { ensureActive(); if (pending.isEmpty()) return@launch }
                    catch (error: Exception) {
                        if (error is ApiFailure && error.status in setOf(401, 426)) {
                            terminal = true
                            if (error.status == 401) mutable.value = LivePhase.UNAUTHORIZED
                            onFailure(error); stream?.cancel(); disconnect(); return@launch
                        }
                        // Failed resources stay required until a later read retries them.
                        required.addAll(next)
                        // A change received during this failed read still earns one follow-up.
                        if (pending.isEmpty()) return@launch
                    }
                }
                if (ready && current == epoch && required.isEmpty()) mutable.value = LivePhase.LIVE
            } finally { if (current == epoch) reader = null }
        }
    }

    fun stop() { foreground = false; stream?.cancel(); stream = null; disconnect(); versions.clear() }
}
