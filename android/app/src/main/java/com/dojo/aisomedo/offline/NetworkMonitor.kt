package com.dojo.aisomedo.offline

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

data class NetworkStatus(val connected: Boolean = false, val epoch: Long = 0)

internal class NetworkTracker {
    private var current: Any? = null
    private val mutable = MutableStateFlow(NetworkStatus())
    val state = mutable.asStateFlow()
    @Synchronized fun available(key: Any) {
        if (key == current) return
        current = key
        mutable.value = NetworkStatus(false, mutable.value.epoch + 1)
    }
    @Synchronized fun capabilities(key: Any, internet: Boolean, validated: Boolean) {
        if (key != current) return
        val connected = internet && validated
        if (connected != mutable.value.connected) mutable.value = NetworkStatus(connected, mutable.value.epoch + 1)
    }
    @Synchronized fun lost(key: Any) {
        if (current == null && mutable.value.epoch == 0L) {
            mutable.value = NetworkStatus(false, 1)
            return
        }
        if (key != current) return
        current = null
        mutable.value = NetworkStatus(false, mutable.value.epoch + 1)
    }
    @Synchronized fun initialize(key: Any?, internet: Boolean, validated: Boolean) {
        if (mutable.value.epoch != 0L || key == null) return
        available(key); capabilities(key, internet, validated)
    }
}

class NetworkMonitor(context: Context) : AutoCloseable {
    private val manager = context.applicationContext.getSystemService(ConnectivityManager::class.java)
    private val tracker = NetworkTracker()
    val state = tracker.state
    @Volatile private var closed = false
    private var registered = false
    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) { if (!closed) tracker.available(network) }
        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) {
            if (!closed) tracker.capabilities(network, capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET),
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))
        }
        override fun onLost(network: Network) { if (!closed) tracker.lost(network) }
    }
    init {
        try {
            manager.registerDefaultNetworkCallback(callback)
            registered = true
            val network = manager.activeNetwork
            val capabilities = network?.let(manager::getNetworkCapabilities)
            tracker.initialize(network, capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true,
                capabilities?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true)
        } catch (_: Exception) { close() }
    }
    @Synchronized override fun close() {
        if (closed) return
        closed = true
        if (registered) runCatching { manager.unregisterNetworkCallback(callback) }
        tracker.available(Any())
    }
}
