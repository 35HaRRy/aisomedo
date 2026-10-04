package com.dojo.aisomedo.onboarding

import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.dojo.aisomedo.api.ConsentOut
import com.dojo.aisomedo.ui.DojoTheme
import org.junit.*

class OnboardingTest {
    @get:Rule val compose = createComposeRule()
    @Test fun policyStartsUncheckedAndVersionChangeRequiresNewAcknowledgement() {
        val policy = mutableStateOf(ConsentOut(null, "Politika tam metni", 1))
        var posted: Int? = null
        compose.setContent { DojoTheme { ConsentStep(policy.value, false) { posted = it } } }
        compose.onNodeWithText("Politika tam metni").assertExists()
        compose.onNodeWithTag("consent-acknowledgement").assertIsOff()
        compose.onNodeWithText("Bu sürümü kabul et").assertIsNotEnabled()
        compose.onNodeWithTag("consent-acknowledgement").performClick()
        compose.runOnIdle { policy.value = ConsentOut(null, "Yeni metin", 2) }
        compose.onNodeWithTag("consent-acknowledgement").assertIsOff().performClick()
        compose.onNodeWithText("Bu sürümü kabul et").performClick()
        Assert.assertEquals(2, posted)
    }
    @Test fun inheritedAcceptanceHasNoSecondSubmit() {
        compose.setContent { DojoTheme { ConsentStep(ConsentOut("2026-10-05T12:00:00Z", "Politika", 1), false) {} } }
        compose.onNodeWithTag("consent-acknowledgement").assertDoesNotExist()
        compose.onNodeWithText("Bu sürümü kabul et").assertDoesNotExist()
    }
}
