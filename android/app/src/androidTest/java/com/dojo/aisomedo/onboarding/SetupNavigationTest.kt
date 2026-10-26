package com.dojo.aisomedo.onboarding

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.dojo.aisomedo.ui.DojoTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class SetupNavigationTest {
    @get:Rule val compose = createComposeRule()

    @Test fun finishReplacesLaterAndCannotSubmitWhileOffline() {
        val ready = mutableStateOf(false)
        val writable = mutableStateOf(true)
        var finished = 0
        var deferred = 0
        compose.setContent {
            DojoTheme {
                Box(Modifier.requiredWidth(320.dp)) {
                    SetupNavigation(ready.value, writable.value, false, true, {}, { finished++ }, { deferred++ })
                }
            }
        }
        compose.onNodeWithText("Kuruluma sonra devam et").performClick()
        compose.runOnIdle { assertEquals(1, deferred); ready.value = true }
        compose.onNodeWithText("Kuruluma sonra devam et").assertDoesNotExist()
        compose.onNodeWithText("Kurulumu bitir").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(1, finished); writable.value = false }
        compose.onNodeWithText("Kurulumu bitir").assertIsNotEnabled()
    }
}
