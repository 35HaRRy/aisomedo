package com.dojo.aisomedo.ui

import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ActivityActorTest {
    @Test fun actorUsesLiteralOrResolvedClientWithoutInventingName() {
        assertEquals("system", activityActorLabel(Json.parseToJsonElement("\"system\"")))
        assertEquals("Telefon", activityActorLabel(Json.parseToJsonElement("""{"id":1,"name":"Telefon","kind":"device"}""")))
        assertEquals("Telefon", activityActorLabel(Json.parseToJsonElement("""{"id":1,"name":"Telefon","kind":"device","future_field":true}""")))
        for (text in listOf("null", "false", "1", "{}", "\"\"")) assertNull(activityActorLabel(Json.parseToJsonElement(text)))
    }
}
