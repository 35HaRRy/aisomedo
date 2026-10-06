package com.dojo.aisomedo.api

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class GeneratedApiTest {
    @Test fun compatibilityConstructorKeepsItsOriginalArgumentOrder() {
        val compat = CompatInfo("0.1.0", 1, 2, "https://example.com/update")
        assertEquals("0.1.0", compat.apiVersion)
        assertEquals(1, compat.androidMinVersionCode)
    }
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = true }

    @Test fun requiredNullableFieldCannotBeOmitted() {
        val valid = """{"generated_at":"2026-10-05T12:00:00Z","package":null,"next_slot":null,"pending_actions":[],"plan":{"anchor_date":null,"anchor_time":null,"enabled":false,"timezone":"Europe/Istanbul"},"instagram":{"health":"unknown"},"worker":{"phase":null,"status":"unknown"}}"""
        assertNull(json.decodeFromString<DashboardOut>(valid).`package`)
        assertThrows(SerializationException::class.java) {
            json.decodeFromString<DashboardOut>(valid.replace("\"package\":null,", ""))
        }
    }

    @Test fun defaultsAndAdditiveFieldsSurviveDecoding() {
        val setup = json.decodeFromString<SetupOut>("""{"checklist":[{"key":"consent","label":"Consent","complete":false,"new_field":1}],"ready":false}""")
        assertTrue(setup.checklist.single().required)
        val compat = json.decodeFromString<CompatInfo>("""{"api_version":"0.1.0","android_min_version_code":1,"android_current_version_code":2,"update_url":"https://example.com/update"}""")
        assertEquals(1, compat.androidMinVersionCode)
        assertEquals(2, compat.androidCurrentVersionCode)
    }
}
