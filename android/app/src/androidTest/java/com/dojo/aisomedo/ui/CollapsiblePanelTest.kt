package com.dojo.aisomedo.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.TextField
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Rule
import org.junit.Test

class CollapsiblePanelTest {
    @get:Rule val compose = createComposeRule()

    @Test fun collapseRetainsDraftAndDoesNotCollapseSibling() {
        compose.setContent { DojoTheme { Column {
            CollapsiblePanel("Paket") {
                var draft by rememberSaveable { mutableStateOf("") }
                TextField(draft, { draft = it }, Modifier.testTag("draft"))
            }
            CollapsiblePanel("Yüklemeler") { androidx.compose.material3.Text("Yükleme sürüyor") }
        } } }
        compose.onNodeWithTag("draft").performTextInput("Kaydedilmemiş içerik")
        compose.onNodeWithContentDescription("Paket panelini kapat").performClick()
        compose.onNodeWithTag("draft").assertDoesNotExist()
        compose.onNodeWithText("Yükleme sürüyor").assertExists()
        compose.onNodeWithContentDescription("Paket panelini aç").performClick()
        compose.onNodeWithTag("draft").assertTextEquals("Kaydedilmemiş içerik")
    }
}
