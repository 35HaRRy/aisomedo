package com.dojo.aisomedo.uploads

import org.junit.Assert.assertEquals
import org.junit.Test

class UploadSchedulerTest {
    @Test fun routesByPlatformSupport() {
        for (api in listOf(29, 33)) assertEquals(SchedulerKind.WORK_MANAGER, schedulerKind(api))
        for (api in listOf(34, 36)) assertEquals(SchedulerKind.UIDT, schedulerKind(api))
    }
}
