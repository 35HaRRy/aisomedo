package com.dojo.aisomedo.offline

import androidx.test.platform.app.InstrumentationRegistry
import com.dojo.aisomedo.uploads.UploadRuntime
import org.junit.Assert.*
import org.junit.Test

class NetworkMonitorAndroidTest {
    @Test fun closeUnregistersAndRecreationReusesRuntimeMonitor() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val monitor = NetworkMonitor(context)
        monitor.close(); monitor.close()
        assertFalse(monitor.state.value.connected)
        assertSame(UploadRuntime.get(context).network, UploadRuntime.get(context).network)
    }
}
